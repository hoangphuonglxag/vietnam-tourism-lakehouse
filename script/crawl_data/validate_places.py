import json
import re
import uuid
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from shapely.ops import unary_union

from script.crawl_data.pipeline_scope import log_event, utc_now_iso


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

PROVINCES_FILE = DATA_DIR / "provinces.csv"
INPUT_FILE = DATA_DIR / "candidate_places_raw.csv"
OUTPUT_FILE = DATA_DIR / "candidate_places_validated.csv"

TEST_MODE = False
TEST_PROVINCE = "Đà Nẵng"

# Những điểm nằm ngoài boundary nhưng rất gần boundary
# sẽ được đưa vào REVIEW thay vì INVALID.
BOUNDARY_REVIEW_DISTANCE_M = 1000


# ============================================================
# BASIC VALIDATION
# ============================================================

def validate_basic(df):
    """
    Kiểm tra các field cơ bản:
    - Có OSM ID
    - Có tên
    - Có latitude / longitude
    - Tọa độ nằm trong range hợp lệ
    """

    df = df.copy()

    df["validation_status"] = "valid"
    df["validation_reason"] = ""

    # Missing OSM ID
    mask = df["osm_id"].isna()

    df.loc[mask, "validation_status"] = "invalid"
    df.loc[mask, "validation_reason"] = "missing_osm_id"

    # Missing name
    mask = df["place_name"].isna() | (
        df["place_name"].astype(str).str.strip() == ""
    )

    df.loc[mask, "validation_status"] = "invalid"
    df.loc[mask, "validation_reason"] = "missing_name"

    # Missing coordinates
    mask = (
        df["latitude"].isna()
        | df["longitude"].isna()
    )

    df.loc[mask, "validation_status"] = "invalid"
    df.loc[mask, "validation_reason"] = "missing_coordinates"

    # Invalid latitude
    mask = (
        df["latitude"].notna()
        & (
            (df["latitude"] < -90)
            | (df["latitude"] > 90)
        )
    )

    df.loc[mask, "validation_status"] = "invalid"
    df.loc[mask, "validation_reason"] = "invalid_latitude"

    # Invalid longitude
    mask = (
        df["longitude"].notna()
        & (
            (df["longitude"] < -180)
            | (df["longitude"] > 180)
        )
    )

    df.loc[mask, "validation_status"] = "invalid"
    df.loc[mask, "validation_reason"] = "invalid_longitude"

    return df


# ============================================================
# OSM DUPLICATE VALIDATION
# ============================================================

def validate_osm_duplicates(df):
    """
    Một OSM object chỉ nên xuất hiện một lần.
    """

    df = df.copy()

    duplicate = df.duplicated(
        subset=["osm_type", "osm_id"],
        keep="first"
    )

    mask = (
        duplicate
        & (df["validation_status"] == "valid")
    )

    df.loc[mask, "validation_status"] = "invalid"
    df.loc[mask, "validation_reason"] = "duplicate_osm_object"

    return df


# ============================================================
# SUSPICIOUS NAME VALIDATION
# ============================================================

def validate_suspicious_names(df):
    """
    Đánh dấu những tên có khả năng không phải destination thực sự.

    Không loại trực tiếp -> REVIEW.
    """

    df = df.copy()

    patterns = [
        r"^group\s+[a-z0-9]+$",
        r"^block\s+[a-z0-9]+$",
        r"^section\s+[a-z0-9]+$",
        r"^area\s+[a-z0-9]+$",
        r"^zone\s+[a-z0-9]+$",
        r"^a\d+$",
        r"^b\d+$",
        r"^c\d+$",
        r"^d\d+$",
        r"^e\d+$",
        r"^f\d+$",
        r"^g\d+$",
        r"^h\d+$",
    ]

    regex = re.compile(
        "|".join(patterns),
        re.IGNORECASE
    )

    for idx, row in df.iterrows():

        if row["validation_status"] == "invalid":
            continue

        name = str(row["place_name"]).strip()

        if regex.search(name):

            df.at[idx, "validation_status"] = "review"

            if not df.at[idx, "validation_reason"]:
                df.at[idx, "validation_reason"] = (
                    "suspicious_name"
                )

    return df


# ============================================================
# SAME NAME DUPLICATE
# ============================================================

def validate_same_name_duplicates(df):
    """
    Tìm những candidate có cùng tên trong cùng tỉnh.

    Không loại trực tiếp vì cùng tên có thể là:
    - hai địa điểm thật
    - nhiều OSM objects của cùng một địa điểm
    """

    df = df.copy()

    normalized = (
        df["place_name"]
        .fillna("")
        .astype(str)
        .str.lower()
        .str.strip()
    )

    df["_normalized_name"] = normalized

    duplicate = df.duplicated(
        subset=[
            "province_id",
            "_normalized_name"
        ],
        keep=False
    )

    mask = (
        duplicate
        & (df["_normalized_name"] != "")
        & (df["validation_status"] == "valid")
    )

    df.loc[mask, "validation_status"] = "review"
    df.loc[mask, "validation_reason"] = (
        "duplicate_name"
    )

    df.drop(
        columns=["_normalized_name"],
        inplace=True
    )

    return df


# ============================================================
# LOAD GEOJSON
# ============================================================

def load_province_boundary(province):

    url = province["geojson_url"]

    print(
        f"\nLoading province boundary: "
        f"{province['province_name']}"
    )

    gdf = gpd.read_file(url)

    if gdf.empty:
        raise ValueError(
            f"Empty GeoJSON: {province['province_name']}"
        )

    # GeoJSON thông thường là EPSG:4326
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)

    else:
        gdf = gdf.to_crs(epsg=4326)

    # Fix invalid geometry
    gdf["geometry"] = gdf.geometry.buffer(0)

    gdf = gdf[
        gdf.geometry.notna()
        & ~gdf.geometry.is_empty
    ]

    if gdf.empty:
        raise ValueError(
            f"No valid geometry: "
            f"{province['province_name']}"
        )

    return unary_union(gdf.geometry)


# ============================================================
# SPATIAL VALIDATION
# ============================================================

def validate_spatial(df, provinces, run_id):

    df = df.copy()

    df["spatial_status"] = "unknown"
    df["boundary_distance_m"] = None

    log_event(
        "VALIDATE",
        "Loading all province boundaries for spatial join",
        run_id=run_id
    )

    province_gdfs = []

    for idx, row in provinces.iterrows():
        try:
            boundary_geom = load_province_boundary(row)
            province_gdfs.append({
                "province_id": row["province_id"],
                "province_name": row["province_name"],
                "geometry": boundary_geom
            })
        except Exception as e:
            log_event(
                "VALIDATE",
                "Boundary load error (Skipped)",
                run_id=run_id,
                province_name=row["province_name"],
                error=e,
            )

    if not province_gdfs:
        log_event(
            "VALIDATE",
            "No valid boundaries loaded",
            run_id=run_id
        )
        return df

    provinces_gdf = gpd.GeoDataFrame(
        province_gdfs,
        crs="EPSG:4326"
    )

    log_event(
        "VALIDATE",
        "Converting candidates to GeoDataFrame",
        run_id=run_id
    )

    geometry = [
        Point(lon, lat)
        for lon, lat in zip(df["longitude"], df["latitude"])
    ]

    points_gdf = gpd.GeoDataFrame(
        df,
        geometry=geometry,
        crs="EPSG:4326"
    )

    log_event(
        "VALIDATE",
        "Performing spatial join (Point-in-Polygon)",
        run_id=run_id
    )

    # Perform spatial join
    # how='left' keeps all points
    # predicate='intersects' handles point inside polygon properly
    joined = gpd.sjoin(
        points_gdf,
        provinces_gdf,
        how="left",
        predicate="intersects"
    )

    # If point falls on a border exactly shared by two polygons, it might duplicate
    joined = joined[~joined.index.duplicated(keep="first")]

    # Update matches
    matched_mask = joined["province_id_right"].notna()
    
    # Update province_id and province_name definitively from the spatial join
    df.loc[matched_mask, "province_id"] = joined.loc[matched_mask, "province_id_right"]
    df.loc[matched_mask, "province_name"] = joined.loc[matched_mask, "province_name_right"]
    df.loc[matched_mask, "spatial_status"] = "inside"

    # Handle unmatched (outside all provinces)
    unmatched_mask = joined["province_id_right"].isna()
    unmatched_indices = df[unmatched_mask].index

    if not unmatched_indices.empty:
        log_event(
            "VALIDATE",
            "Processing points outside all boundaries",
            run_id=run_id,
            count=len(unmatched_indices)
        )

        provinces_projected = provinces_gdf.to_crs(epsg=3857)
        points_projected = points_gdf.loc[unmatched_indices].to_crs(epsg=3857)
        
        # We find distance to nearest polygon for each unmatched point
        for idx in unmatched_indices:
            point_geom = points_projected.loc[idx, "geometry"]
            distances = provinces_projected.distance(point_geom)
            min_dist_idx = distances.idxmin()
            distance_m = float(distances.loc[min_dist_idx])
            
            df.at[idx, "boundary_distance_m"] = round(distance_m, 2)

            if distance_m <= BOUNDARY_REVIEW_DISTANCE_M:
                df.at[idx, "spatial_status"] = "near_boundary"
                
                nearest_prov = provinces_gdf.loc[min_dist_idx]
                df.at[idx, "province_id"] = nearest_prov["province_id"]
                df.at[idx, "province_name"] = nearest_prov["province_name"]

                if df.at[idx, "validation_status"] != "invalid":
                    df.at[idx, "validation_status"] = "review"
                    df.at[idx, "validation_reason"] = "boundary_uncertain"
            else:
                df.at[idx, "spatial_status"] = "outside"

                if df.at[idx, "validation_status"] != "invalid":
                    df.at[idx, "validation_status"] = "invalid"
                    df.at[idx, "validation_reason"] = "outside_all_provinces"

    return df


# ============================================================
# MAIN
# ============================================================

def main():

    run_id = uuid.uuid4().hex[:12]
    validated_at = utc_now_iso()

    log_event(
        "VALIDATE",
        "Start place validation",
        run_id=run_id,
        input=INPUT_FILE,
        provinces_file=PROVINCES_FILE,
        output=OUTPUT_FILE,
    )

    # --------------------------------------------------------
    # Load
    # --------------------------------------------------------

    provinces = pd.read_csv(
        PROVINCES_FILE,
        dtype={
            "province_id": str
        }
    )

    df = pd.read_csv(
        INPUT_FILE,
        dtype={
            "province_id": str
        }
    )

    log_event(
        "VALIDATE",
        "Input loaded",
        run_id=run_id,
        total_provinces=len(provinces),
        total_candidates=len(df),
    )

    # --------------------------------------------------------
    # Test mode
    # --------------------------------------------------------

    if TEST_MODE:

        log_event(
            "VALIDATE",
            "TEST MODE enabled",
            run_id=run_id,
            test_province=TEST_PROVINCE,
        )

        df = df[
            df["province_name"]
            == TEST_PROVINCE
        ].copy()

    # --------------------------------------------------------
    # Validation pipeline
    # --------------------------------------------------------

    log_event("VALIDATE", "[1/5] Basic validation", run_id=run_id)

    df = validate_basic(df)

    log_event("VALIDATE", "[2/5] OSM duplicate validation", run_id=run_id)

    df = validate_osm_duplicates(df)

    log_event("VALIDATE", "[3/5] Suspicious name validation", run_id=run_id)

    df = validate_suspicious_names(df)

    log_event("VALIDATE", "[4/5] Same-name duplicate validation", run_id=run_id)

    df = validate_same_name_duplicates(df)

    log_event("VALIDATE", "[5/5] Province spatial validation", run_id=run_id)

    df = validate_spatial(
        df,
        provinces,
        run_id=run_id,
    )

    df["validated_at_utc"] = validated_at
    df["pipeline_run_id"] = run_id

    # --------------------------------------------------------
    # Output
    # --------------------------------------------------------

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    df.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # ========================================================
    # REPORT
    # ========================================================

    log_event(
        "VALIDATE",
        "VALIDATION COMPLETED",
        run_id=run_id,
        total_candidates=len(df),
        output=OUTPUT_FILE,
    )

    # --------------------------------------------------------
    # Validation status
    # --------------------------------------------------------

    print("\nValidation status:")

    print(
        df["validation_status"]
        .value_counts()
        .rename_axis("status")
        .reset_index(name="count")
        .to_string(index=False)
    )

    # --------------------------------------------------------
    # Validation reasons
    # --------------------------------------------------------

    print("\nValidation reasons:")

    reasons = (
        df["validation_reason"]
        .replace("", "none")
        .value_counts()
        .rename_axis("reason")
        .reset_index(name="count")
    )

    print(
        reasons.to_string(index=False)
    )

    # --------------------------------------------------------
    # Spatial status
    # --------------------------------------------------------

    print("\nSpatial validation:")

    spatial = (
        df["spatial_status"]
        .value_counts()
        .rename_axis("spatial_status")
        .reset_index(name="count")
    )

    print(
        spatial.to_string(index=False)
    )

    # --------------------------------------------------------
    # Province summary
    # --------------------------------------------------------

    print("\nCandidates by province:")

    province_summary = (
        df.groupby(
            [
                "province_id",
                "province_name"
            ],
            dropna=False
        )
        .size()
        .reset_index(
            name="candidate_count"
        )
    )

    print(
        province_summary.to_string(
            index=False
        )
    )

    # --------------------------------------------------------
    # Sample
    # --------------------------------------------------------

    print("\nSample validated data:")

    sample_columns = [
        "osm_id",
        "place_name",
        "latitude",
        "longitude",
        "province_name",
        "spatial_status",
        "boundary_distance_m",
        "validation_status",
        "validation_reason"
    ]

    sample_columns = [
        c for c in sample_columns
        if c in df.columns
    ]

    print(
        df[sample_columns]
        .head(20)
        .to_string(index=False)
    )

    print("\nDone.")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()