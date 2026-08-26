import json
import re
import time
import requests
import pandas as pd


# ============================================================
# CONFIG
# ============================================================

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

PROVINCES_FILE = "./data/provinces.csv"
OUTPUT_FILE = "./data/candidate_places_raw.csv"

REQUEST_TIMEOUT = 180
OVERPASS_TIMEOUT = 120

USER_AGENT = "TLCN-Tourism-Research/1.0"

# Delay giữa các tỉnh
REQUEST_DELAY = 15

# Retry khi Overpass lỗi
MAX_RETRIES = 3

# Test nếu cần
TEST_MODE = False
TEST_PROVINCE = "Đà Nẵng"


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

def crawl_province(province):

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

    print()
    print("=" * 70)
    print(f"Crawling: {province_name}")
    print("=" * 70)

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            print(
                f"Attempt {attempt}/{MAX_RETRIES}"
            )

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

            elements = data.get(
                "elements",
                []
            )

            print(
                f"OSM elements found: "
                f"{len(elements)}"
            )

            candidates = []

            for element in elements:

                tags = element.get(
                    "tags",
                    {}
                )

                # ------------------------------------------------
                # NAME
                # ------------------------------------------------

                place_name = (
                    tags.get("name")
                    or tags.get("name:vi")
                    or tags.get("name:en")
                )

                if not place_name:
                    continue

                # ------------------------------------------------
                # COORDINATES
                # ------------------------------------------------

                if element["type"] == "node":

                    latitude = element.get("lat")
                    longitude = element.get("lon")

                else:

                    center = element.get(
                        "center",
                        {}
                    )

                    latitude = center.get("lat")
                    longitude = center.get("lon")

                # ------------------------------------------------
                # TAGS
                # ------------------------------------------------

                tourism = tags.get("tourism")
                natural = tags.get("natural")
                historic = tags.get("historic")
                leisure = tags.get("leisure")

                website = (
                    tags.get("website")
                    or tags.get("contact:website")
                )

                wikidata = tags.get("wikidata")
                wikipedia = tags.get("wikipedia")

                # ------------------------------------------------
                # RAW RECORD
                # ------------------------------------------------

                candidates.append({

                    "osm_id":
                        element["id"],

                    "osm_type":
                        element["type"],

                    "place_name":
                        place_name,

                    "name_vi":
                        tags.get("name:vi"),

                    "name_en":
                        tags.get("name:en"),

                    "tourism":
                        tourism,

                    "natural":
                        natural,

                    "historic":
                        historic,

                    "leisure":
                        leisure,

                    "latitude":
                        latitude,

                    "longitude":
                        longitude,

                    "province_id":
                        province["province_id"],

                    "province_name":
                        province_name,

                    "website":
                        website,

                    "wikidata":
                        wikidata,

                    "wikipedia":
                        wikipedia,

                    "tags_json":
                        json.dumps(
                            tags,
                            ensure_ascii=False
                        ),

                    "source":
                        "OpenStreetMap"
                })

            df = pd.DataFrame(
                candidates
            )

            print(
                f"Candidates with name: "
                f"{len(df)}"
            )

            return df

        except Exception as e:

            print(
                f"ERROR: {e}"
            )

            if attempt < MAX_RETRIES:

                wait_time = 30 * attempt

                print(
                    f"Waiting "
                    f"{wait_time}s "
                    f"before retry..."
                )

                time.sleep(
                    wait_time
                )

            else:

                print(
                    f"FAILED: "
                    f"{province_name}"
                )

                return pd.DataFrame()


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print(
        "OSM MISSING PROVINCES CRAWLER"
    )
    print("=" * 70)

    # --------------------------------------------------------
    # LOAD PROVINCES
    # --------------------------------------------------------

    provinces = pd.read_csv(
        PROVINCES_FILE,
        dtype={
            "province_id": str
        }
    )

    print(
        f"Total provinces loaded: "
        f"{len(provinces)}"
    )

    # --------------------------------------------------------
    # LOAD EXISTING CANDIDATES
    # --------------------------------------------------------

    try:

        existing = pd.read_csv(
            OUTPUT_FILE,
            dtype={
                "province_id": str,
                "osm_id": str,
                "osm_type": str
            }
        )

        print(
            f"Existing candidates: "
            f"{len(existing)}"
        )

    except FileNotFoundError:

        print(
            "candidate_places_raw.csv "
            "not found."
        )

        existing = pd.DataFrame()

    # --------------------------------------------------------
    # FIND EXISTING PROVINCE IDS
    # --------------------------------------------------------

    if not existing.empty:

        existing_province_ids = set(
            existing["province_id"]
            .dropna()
            .astype(str)
            .str.strip()
        )

    else:

        existing_province_ids = set()

    provinces["province_id"] = (
        provinces["province_id"]
        .astype(str)
        .str.strip()
    )

    # --------------------------------------------------------
    # FIND MISSING PROVINCES
    # --------------------------------------------------------

    missing = provinces[
        ~provinces["province_id"].isin(
            existing_province_ids
        )
    ].copy()

    # --------------------------------------------------------
    # TEST MODE
    # --------------------------------------------------------

    if TEST_MODE:

        missing = missing[
            missing["province_name"]
            == TEST_PROVINCE
        ]

    print()
    print("=" * 70)
    print("PROVINCES TO CRAWL")
    print("=" * 70)

    print(
        f"Missing provinces: "
        f"{len(missing)}"
    )

    if missing.empty:

        print(
            "Nothing to crawl."
        )

        return

    print()

    for _, province in missing.iterrows():

        print(
            f"- "
            f"{province['province_id']} "
            f"{province['province_name']}"
        )

    # --------------------------------------------------------
    # CRAWL
    # --------------------------------------------------------

    new_candidates = []

    for i, (_, province) in enumerate(
        missing.iterrows(),
        start=1
    ):

        print()
        print(
            f"[{i}/{len(missing)}] "
            f"{province['province_name']}"
        )

        df = crawl_province(
            province
        )

        if not df.empty:

            new_candidates.append(
                df
            )

        else:

            print(
                "No data returned. "
                "Province will remain "
                "missing and can be retried."
            )

        # ----------------------------------------------------
        # DELAY
        # ----------------------------------------------------

        if i < len(missing):

            print(
                f"Waiting "
                f"{REQUEST_DELAY}s..."
            )

            time.sleep(
                REQUEST_DELAY
            )

    # --------------------------------------------------------
    # NOTHING NEW
    # --------------------------------------------------------

    if not new_candidates:

        print()
        print(
            "No new candidates collected."
        )

        return

    # --------------------------------------------------------
    # COMBINE
    # --------------------------------------------------------

    new_df = pd.concat(
        new_candidates,
        ignore_index=True
    )

    print()
    print(
        f"New candidates: "
        f"{len(new_df)}"
    )

    # --------------------------------------------------------
    # MERGE WITH EXISTING
    # --------------------------------------------------------

    if not existing.empty:

        final_df = pd.concat(
            [
                existing,
                new_df
            ],
            ignore_index=True
        )

    else:

        final_df = new_df

    # --------------------------------------------------------
    # OSM ID DEDUPLICATION
    # --------------------------------------------------------

    final_df = (
        final_df
        .drop_duplicates(
            subset=[
                "osm_type",
                "osm_id"
            ],
            keep="first"
        )
        .reset_index(drop=True)
    )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    final_df.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print()
    print("=" * 70)
    print("CRAWL COMPLETED")
    print("=" * 70)

    print(
        f"Previous candidates: "
        f"{len(existing)}"
    )

    print(
        f"New candidates: "
        f"{len(new_df)}"
    )

    print(
        f"Final candidates: "
        f"{len(final_df)}"
    )

    print(
        f"Output: "
        f"{OUTPUT_FILE}"
    )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print()
    print(
        "Candidates by province:"
    )

    province_counts = (
        final_df
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


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()