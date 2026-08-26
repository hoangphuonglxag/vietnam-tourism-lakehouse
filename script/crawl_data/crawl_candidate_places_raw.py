import json
import random
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

from source.pipeline_scope import (
    SCOPE_LEGACY_63,
    ensure_scope,
    log_event,
    utc_now_iso,
)


# ============================================================
# CONFIG
# ============================================================

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

PROVINCES_FILE = "./data/provinces.csv"
OUTPUT_FILE = "./data/candidate_places_raw.csv"

# True  -> chỉ crawl 1 tỉnh để test
# False -> crawl toàn bộ tỉnh trong PROVINCES_FILE
TEST_MODE = False
TEST_PROVINCE = "Đà Nẵng"

REQUEST_TIMEOUT = 180
OVERPASS_TIMEOUT = 120

USER_AGENT = "TLCN-Tourism-Research/1.0"

# Worker settings for province-level crawling.
MAX_WORKERS = 8
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
REQUEST_JITTER_MIN_SECONDS = 0.3
REQUEST_JITTER_MAX_SECONDS = 1.2

# Scope của job discovery theo pipeline.
DISCOVERY_SCOPE = SCOPE_LEGACY_63

# Nếu đặt current_34 hoặc legacy_63 thì script sẽ cảnh báo
# khi scope trong provinces.csv không khớp.
EXPECTED_PROVINCE_SCOPE = None


# ============================================================
# OSM TAGS
# ============================================================

OSM_TAGS = {
    "tourism": [
        "attraction",
        "museum",
        "viewpoint",
        "theme_park",
        "zoo",
        "aquarium",
        "gallery",
        "arts_centre",
        "artwork"
    ],
    "natural": [
        "peak",
        "waterfall",
        "cave_entrance",
        "beach",
        "cape",
        "cliff",
        "spring",
        "hot_spring"
    ],
    "historic": [
        "monument",
        "memorial",
        "castle",
        "fort",
        "ruins",
        "archaeological_site",
        "building",
        "heritage"
    ],
    "leisure": [
        "park",
        "water_park",
        "garden",
        "nature_reserve"
    ]
}


# ============================================================
# BUILD OVERPASS QUERY
# ============================================================

def build_overpass_query(bbox):

    queries = []

    for tag_type, values in OSM_TAGS.items():

        regex = "|".join(
            re.escape(value)
            for value in values
        )

        queries.append(
            f'nwr["{tag_type}"~"^({regex})$"]({bbox});'
        )

    query = f"""
    [out:json][timeout:{OVERPASS_TIMEOUT}];

    (
        {"".join(queries)}
    );

    out center tags;
    """

    return query


# ============================================================
# CRAWL ONE PROVINCE
# ============================================================

def crawl_province(
    province,
    run_id,
    discovery_scope,
    index,
    total,
    worker_id,
):

    province_name = province["province_name"]

    min_lon = float(province["min_lon"])
    min_lat = float(province["min_lat"])
    max_lon = float(province["max_lon"])
    max_lat = float(province["max_lat"])

    bbox = (
        f"{min_lat},"
        f"{min_lon},"
        f"{max_lat},"
        f"{max_lon}"
    )

    query = build_overpass_query(bbox)

    log_event(
        "DISCOVERY",
        "Start province crawl",
        run_id=run_id,
        worker_id=worker_id,
        progress=f"{index}/{total}",
        province_id=province.get("province_id"),
        province_name=province_name,
    )

    data = None

    for attempt in range(1, MAX_RETRIES + 1):

        # Add small jitter to avoid burst traffic to Overpass.
        time.sleep(
            random.uniform(
                REQUEST_JITTER_MIN_SECONDS,
                REQUEST_JITTER_MAX_SECONDS,
            )
        )

        try:

            response = requests.post(
                OVERPASS_URL,
                data={"data": query},
                headers={
                    "User-Agent": USER_AGENT
                },
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            data = response.json()
            break

        except Exception as error:

            if attempt >= MAX_RETRIES:
                raise

            backoff_seconds = RETRY_BACKOFF_SECONDS * attempt

            log_event(
                "DISCOVERY",
                "Retry province crawl after error",
                run_id=run_id,
                worker_id=worker_id,
                province_id=province.get("province_id"),
                province_name=province_name,
                attempt=f"{attempt}/{MAX_RETRIES}",
                wait_seconds=backoff_seconds,
                error=error,
            )

            time.sleep(backoff_seconds)

    elements = data.get("elements", [])

    log_event(
        "DISCOVERY",
        "OSM elements fetched",
        run_id=run_id,
        worker_id=worker_id,
        province_name=province_name,
        element_count=len(elements),
    )

    candidates = []

    for element in elements:

        tags = element.get("tags", {})

        place_name = (
            tags.get("name")
            or tags.get("name:vi")
            or tags.get("name:en")
        )

        if not place_name:
            continue

        if element["type"] == "node":
            latitude = element.get("lat")
            longitude = element.get("lon")
        else:
            center = element.get("center", {})
            latitude = center.get("lat")
            longitude = center.get("lon")

        tourism = tags.get("tourism")
        natural = tags.get("natural")
        historic = tags.get("historic")
        leisure = tags.get("leisure")

        website = (
            tags.get("website")
            or tags.get("contact:website")
        )

        candidates.append({
            "osm_id": element["id"],
            "osm_type": element["type"],
            "place_name": place_name,
            "name_vi": tags.get("name:vi"),
            "name_en": tags.get("name:en"),
            "tourism": tourism,
            "natural": natural,
            "historic": historic,
            "leisure": leisure,
            "latitude": latitude,
            "longitude": longitude,
            "province_id": province["province_id"],
            "province_name": province_name,
            "website": website,
            "wikidata": tags.get("wikidata"),
            "wikipedia": tags.get("wikipedia"),
            "tags_json": json.dumps(tags, ensure_ascii=False),
            "source": "OpenStreetMap",
            "discovery_scope": discovery_scope,
            "province_scope": province.get("admin_scope"),
            "pipeline_run_id": run_id,
            "crawled_at_utc": utc_now_iso(),
        })

    df = pd.DataFrame(candidates)

    log_event(
        "DISCOVERY",
        "Province crawl completed",
        run_id=run_id,
        worker_id=worker_id,
        province_name=province_name,
        candidates_with_name=len(df),
    )

    return df


# ============================================================
# SUMMARY
# ============================================================

def print_summary(df, run_id):

    log_event(
        "DISCOVERY",
        "CRAWL COMPLETED",
        run_id=run_id,
        total_candidates=len(df),
        output=OUTPUT_FILE,
    )

    print()
    print("Candidates by province:")

    province_counts = (
        df
        .groupby(
            [
                "province_id",
                "province_name"
            ]
        )
        .size()
        .reset_index(
            name="candidate_count"
        )
        .sort_values(
            "candidate_count",
            ascending=False
        )
    )

    print(
        province_counts.to_string(
            index=False
        )
    )

    print()
    print("Candidates by OSM tag:")

    tag_rows = []

    for tag_type in [
        "tourism",
        "natural",
        "historic",
        "leisure"
    ]:

        counts = (
            df[tag_type]
            .dropna()
            .value_counts()
        )

        for tag_value, count in counts.items():

            tag_rows.append({
                "tag_type": tag_type,
                "tag_value": tag_value,
                "count": int(count)
            })

    if tag_rows:

        tag_counts = (
            pd.DataFrame(tag_rows)
            .sort_values(
                ["tag_type", "count"],
                ascending=[True, False]
            )
        )

        print(
            tag_counts.to_string(
                index=False
            )
        )

    else:
        print("No OSM tags found.")


# ============================================================
# MAIN
# ============================================================

def main():

    run_id = uuid.uuid4().hex[:12]
    discovery_scope = ensure_scope(
        DISCOVERY_SCOPE,
        config_name="DISCOVERY_SCOPE"
    )

    log_event(
        "DISCOVERY",
        "Start raw OSM candidate discovery",
        run_id=run_id,
        discovery_scope=discovery_scope,
        province_file=PROVINCES_FILE,
        output=OUTPUT_FILE,
    )

    df_provinces = pd.read_csv(
        PROVINCES_FILE,
        dtype={
            "province_id": str
        }
    )

    log_event(
        "DISCOVERY",
        "Province list loaded",
        run_id=run_id,
        total_provinces=len(df_provinces),
    )

    if EXPECTED_PROVINCE_SCOPE and "admin_scope" in df_provinces.columns:
        expected_scope = ensure_scope(
            EXPECTED_PROVINCE_SCOPE,
            config_name="EXPECTED_PROVINCE_SCOPE"
        )
        existing_scopes = sorted(
            set(
                str(v).strip().lower()
                for v in df_provinces["admin_scope"].dropna().unique()
            )
        )

        if existing_scopes and expected_scope not in existing_scopes:
            log_event(
                "DISCOVERY",
                "WARNING province scope mismatch",
                run_id=run_id,
                expected_scope=expected_scope,
                found_scopes=existing_scopes,
            )

    if TEST_MODE:
        log_event(
            "DISCOVERY",
            "TEST MODE enabled",
            run_id=run_id,
            test_province=TEST_PROVINCE,
        )

        provinces = df_provinces[
            df_provinces["province_name"]
            == TEST_PROVINCE
        ]

        if provinces.empty:
            raise ValueError(
                f"Province not found: "
                f"{TEST_PROVINCE}"
            )
    else:
        provinces = df_provinces

    log_event(
        "DISCOVERY",
        "Provinces selected for crawling",
        run_id=run_id,
        selected_count=len(provinces),
    )

    all_candidates = []
    total_provinces = len(provinces)

    max_workers = max(1, min(MAX_WORKERS, total_provinces))

    log_event(
        "DISCOVERY",
        "Starting province workers",
        run_id=run_id,
        workers=max_workers,
        retries=MAX_RETRIES,
    )

    province_rows = list(provinces.iterrows())
    completed_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:

        futures = {}

        for index, (_, province) in enumerate(province_rows, start=1):

            province = province.copy()
            worker_id = f"W{((index - 1) % max_workers) + 1:02d}"

            future = executor.submit(
                crawl_province,
                province,
                run_id,
                discovery_scope,
                index,
                total_provinces,
                worker_id,
            )

            futures[future] = province

        for future in as_completed(futures):

            province = futures[future]
            completed_count += 1

            try:
                df = future.result()

                if not df.empty:
                    all_candidates.append(df)

                log_event(
                    "DISCOVERY",
                    "Worker finished province",
                    run_id=run_id,
                    completed=f"{completed_count}/{total_provinces}",
                    province_id=province.get("province_id"),
                    province_name=province.get("province_name"),
                    records=len(df),
                )

            except Exception as error:
                log_event(
                    "DISCOVERY",
                    "ERROR province crawl failed",
                    run_id=run_id,
                    completed=f"{completed_count}/{total_provinces}",
                    province_name=province.get("province_name"),
                    error=error,
                )

    if not all_candidates:
        log_event(
            "DISCOVERY",
            "No candidates found",
            run_id=run_id,
        )
        return

    df_places = pd.concat(
        all_candidates,
        ignore_index=True
    )

    # Chỉ loại duplicate tuyệt đối theo OSM object.
    df_places = (
        df_places
        .drop_duplicates(
            subset=[
                "osm_type",
                "osm_id"
            ]
        )
        .reset_index(drop=True)
    )

    df_places.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    log_event(
        "DISCOVERY",
        "Raw candidates saved",
        run_id=run_id,
        records=len(df_places),
        output=OUTPUT_FILE,
    )

    print_summary(df_places, run_id=run_id)


if __name__ == "__main__":
    main()
