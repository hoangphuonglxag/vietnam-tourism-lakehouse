import requests
import pandas as pd

from source.pipeline_scope import (
    SCOPE_CURRENT_34,
    ensure_scope,
    log_event,
    utc_now_iso,
)


# ============================================================
# CONFIG
# ============================================================

GITHUB_API_URL = (
    "https://api.github.com/repos/"
    "thanglequoc/vietnamese-provinces-database/"
    "contents/json/geojson"
)

RAW_BASE_URL = (
    "https://raw.githubusercontent.com/"
    "thanglequoc/vietnamese-provinces-database/"
    "master/json/geojson"
)

OUTPUT_FILE = "./data/provinces.csv"

# Scope của bộ địa giới hành chính đang crawl.
ADMIN_SCOPE = SCOPE_CURRENT_34
PROVINCE_SET_VERSION = "vn_admin_current_34"


# ============================================================
# GET PROVINCE FOLDERS
# ============================================================

def main():

    scope = ensure_scope(
        ADMIN_SCOPE,
        config_name="ADMIN_SCOPE"
    )

    run_started_at = utc_now_iso()

    log_event(
        "PROVINCES",
        "Start crawling province boundary metadata",
        scope=scope,
        source="github_geojson",
        output=OUTPUT_FILE,
    )

    response = requests.get(
        GITHUB_API_URL,
        headers={
            "User-Agent": "TLCN-Tourism-Research/1.0"
        },
        timeout=30
    )

    response.raise_for_status()

    items = response.json()

    # Chỉ lấy folder tỉnh
    province_folders = [
        item
        for item in items
        if item["type"] == "dir"
    ]

    log_event(
        "PROVINCES",
        "Province folders discovered",
        total_folders=len(province_folders),
    )

    data = []

    for idx, folder in enumerate(province_folders, start=1):

        folder_name = folder["name"]

        log_event(
            "PROVINCES",
            "Reading province geojson",
            progress=f"{idx}/{len(province_folders)}",
            folder=folder_name,
        )

        # Ví dụ: 48_da_nang -> 48_da_nang.geojson
        geojson_url = (
            f"{RAW_BASE_URL}/"
            f"{folder_name}/"
            f"{folder_name}.geojson"
        )

        response = requests.get(
            geojson_url,
            headers={
                "User-Agent": "TLCN-Tourism-Research/1.0"
            },
            timeout=30
        )

        if response.status_code != 200:
            log_event(
                "PROVINCES",
                "Skip province due to fetch error",
                status_code=response.status_code,
                geojson_url=geojson_url,
            )
            continue

        geojson = response.json()
        bbox = geojson.get("bbox")

        features = geojson.get("features", [])

        if not features:
            log_event(
                "PROVINCES",
                "Skip province due to empty features",
                geojson_url=geojson_url,
            )
            continue

        feature = features[0]
        properties = feature.get("properties", {})

        province_id = (
            feature.get("id")
            or properties.get("province_code")
            or properties.get("code")
        )

        province_name = (
            properties.get("name")
            or properties.get("province_name")
            or properties.get("full_name")
        )

        feature_bbox = feature.get("bbox")

        if feature_bbox:
            bbox = feature_bbox

        data.append({
            "province_id": province_id,
            "province_name": province_name,
            "min_lon": bbox[0] if bbox else None,
            "min_lat": bbox[1] if bbox else None,
            "max_lon": bbox[2] if bbox else None,
            "max_lat": bbox[3] if bbox else None,
            "geojson_url": geojson_url,
            "admin_scope": scope,
            "province_set_version": PROVINCE_SET_VERSION,
            "fetched_at_utc": run_started_at,
        })

    df = pd.DataFrame(data)

    log_event(
        "PROVINCES",
        "Province dataframe created",
        total_provinces=len(df),
    )

    df.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    log_event(
        "PROVINCES",
        "Saved province metadata",
        output=OUTPUT_FILE,
    )


if __name__ == "__main__":
    main()