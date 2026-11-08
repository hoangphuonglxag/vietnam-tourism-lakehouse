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
    "silver_youtube_comments",
    "silver_google_maps_rating_snapshots",
    "silver_place_temporal_coverage",
]


def ensure_warehouse() -> None:
    """
    Ensure Lakekeeper is bootstrapped and the target warehouse exists
    pointing to s3://<S3_BUCKET>/<S3_KEY_PREFIX> on MinIO.
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

    if any(w.get("name") == WAREHOUSE for w in warehouses):
        return

    print(f"Creating Lakekeeper warehouse '{WAREHOUSE}' -> s3://{S3_BUCKET}/{S3_KEY_PREFIX}")
    payload = {
        "warehouse-name": WAREHOUSE,
        "project-id": project_id,
        "storage-profile": {
            "type": "s3",
            "bucket": S3_BUCKET,
            "key-prefix": S3_KEY_PREFIX,
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


def get_catalog():
    """
    Connect to Lakekeeper's Iceberg REST Catalog (auto-initializing the warehouse if needed).
    """
    ensure_warehouse()

    catalog = load_catalog(
        CATALOG_NAME,
        **{
            "type": "rest",
            "uri": LAKEKEEPER_URI,
            "warehouse": WAREHOUSE,
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

    catalog = get_catalog()

    print()
    print("Catalog connected successfully.")
    print()
    print("Namespaces:")

    namespaces = catalog.list_namespaces()
    for namespace in namespaces:
        print(f"  - {namespace}")

    if not catalog.namespace_exists(NAMESPACE):
        print()
        print(f"Creating namespace: {NAMESPACE}")
        catalog.create_namespace(NAMESPACE)
    else:
        print()
        print(f"Namespace already exists: {NAMESPACE}")

    print()
    print("========================================")
    print("Lakekeeper catalog connection OK")
    print("========================================")


if __name__ == "__main__":
    main()
