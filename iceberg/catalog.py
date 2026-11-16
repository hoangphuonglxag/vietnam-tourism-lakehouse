import os
import requests
from pyiceberg.catalog import load_catalog


CATALOG_NAME = "lakekeeper"

LAKEKEEPER_URI = os.getenv("LAKEKEEPER_URI", "http://localhost:8181/catalog")
LAKEKEEPER_BASE_URL = LAKEKEEPER_URI.removesuffix("/catalog").rstrip("/")

WAREHOUSE = os.getenv("ICEBERG_WAREHOUSE", "tourism_warehouse")
NAMESPACE = os.getenv("ICEBERG_NAMESPACE", "silver")

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
S3_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "lakehouse_admin")
S3_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "minIO123")
S3_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET = os.getenv("ICEBERG_S3_BUCKET", "lakehouse")
S3_KEY_PREFIX = os.getenv("ICEBERG_S3_PREFIX", "silver")

SILVER_TABLES = [
    "silver_provinces",
    "silver_taxonomy",
    "silver_places",
    "silver_place_categories",
    "silver_travel_reviews",
    "silver_youtube_videos",
    "silver_youtube_video_snapshots",
    "silver_youtube_comments",
    "silver_google_maps_rating_snapshots",
    "silver_place_temporal_coverage",
]

GOLD_TABLES = [
    "gold_fct_place_monthly_growth",
    "gold_fct_place_snapshot_trajectory",
    "gold_obt_place_360_profile",
    "gold_fct_youtube_video_performance",
    "gold_fct_province_tourism_summary",
    "gold_fct_category_tourism_summary",
]

LAYER_CONFIGS = {
    "silver": {
        "warehouse": WAREHOUSE,
        "namespace": NAMESPACE,
        "s3_prefix": S3_KEY_PREFIX,
        "tables": SILVER_TABLES,
    },
    "gold": {
        "warehouse": WAREHOUSE,
        "namespace": os.getenv("ICEBERG_GOLD_NAMESPACE", "gold"),
        "s3_prefix": S3_KEY_PREFIX,
        "tables": GOLD_TABLES,
    },
}


def get_layer_config(layer: str = "silver") -> dict:
    """Return warehouse, namespace, s3_prefix, and table list for the given layer."""
    normalized = layer.strip().lower()
    if normalized not in LAYER_CONFIGS:
        raise ValueError(f"Unsupported layer '{layer}'. Choose from: {list(LAYER_CONFIGS.keys())}")
    return LAYER_CONFIGS[normalized]


def ensure_warehouse(warehouse_name: str = WAREHOUSE, s3_prefix: str = S3_KEY_PREFIX) -> None:
    """
    Ensure Lakekeeper is bootstrapped and the target warehouse exists
    pointing to s3://<S3_BUCKET>/<s3_prefix> on MinIO.
    """
    info_resp = requests.get(f"{LAKEKEEPER_BASE_URL}/management/v1/info", timeout=15)
    info_resp.raise_for_status()
    info = info_resp.json()

    if not info.get("bootstrapped"):
        boot_resp = requests.post(
            f"{LAKEKEEPER_BASE_URL}/management/v1/bootstrap",
            json={"accept-terms-of-use": True},
            timeout=15,
        )
        boot_resp.raise_for_status()
        info = requests.get(f"{LAKEKEEPER_BASE_URL}/management/v1/info", timeout=15).json()

    project_id = info.get("default-project-id", "00000000-0000-0000-0000-000000000000")

    wh_resp = requests.get(f"{LAKEKEEPER_BASE_URL}/management/v1/warehouse", timeout=15)
    wh_resp.raise_for_status()
    warehouses = wh_resp.json().get("warehouses", [])

    if any(w.get("name") == warehouse_name for w in warehouses):
        return

    print(f"Creating Lakekeeper warehouse '{warehouse_name}' -> s3://{S3_BUCKET}/{s3_prefix}")
    payload = {
        "warehouse-name": warehouse_name,
        "project-id": project_id,
        "storage-profile": {
            "type": "s3",
            "bucket": S3_BUCKET,
            "key-prefix": s3_prefix,
            "region": S3_REGION,
            "endpoint": S3_ENDPOINT,
            "path-style-access": True,
            "flavor": "minio",
            "sts-enabled": False,
            "storage-layout": {
                "type": "tabular-only",
                "tabular": "{name}-{uuid}",
            },
        },
        "storage-credential": {
            "type": "s3",
            "credential-type": "access-key",
            "aws-access-key-id": S3_ACCESS_KEY,
            "aws-secret-access-key": S3_SECRET_KEY,
        },
    }
    create_resp = requests.post(
        f"{LAKEKEEPER_BASE_URL}/management/v1/warehouse",
        json=payload,
        timeout=15,
    )
    create_resp.raise_for_status()


def get_catalog(layer: str = "silver"):
    """
    Connect to Lakekeeper's Iceberg REST Catalog for the specified layer
    (auto-initializing the warehouse if needed).
    """
    cfg = get_layer_config(layer)
    ensure_warehouse(warehouse_name=cfg["warehouse"], s3_prefix=cfg["s3_prefix"])

    catalog = load_catalog(
        f"{CATALOG_NAME}_{layer}",
        **{
            "type": "rest",
            "uri": LAKEKEEPER_URI,
            "warehouse": cfg["warehouse"],
            "s3.endpoint": S3_ENDPOINT,
            "s3.access-key-id": S3_ACCESS_KEY,
            "s3.secret-access-key": S3_SECRET_KEY,
            "s3.region": S3_REGION,
        },
    )

    return catalog


def main():
    print()
    print("========================================")
    print("Testing Lakekeeper REST Catalog")
    print("========================================")

    for layer_name, cfg in LAYER_CONFIGS.items():
        catalog = get_catalog(layer_name)
        ns = cfg["namespace"]

        print()
        print(f"Layer '{layer_name}' -> Warehouse '{cfg['warehouse']}' connected.")
        if not catalog.namespace_exists(ns):
            print(f"  Creating namespace: {ns}")
            catalog.create_namespace(ns)
        else:
            print(f"  Namespace already exists: {ns}")

    print()
    print("========================================")
    print("Lakekeeper catalog connection OK")
    print("========================================")


if __name__ == "__main__":
    main()
