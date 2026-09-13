import os

from pyiceberg.catalog import load_catalog


CATALOG_NAME = "lakekeeper"

LAKEKEEPER_URI = os.getenv("LAKEKEEPER_URI", "http://localhost:8181/catalog")

WAREHOUSE = os.getenv("ICEBERG_WAREHOUSE", "tourism_warehouse")

NAMESPACE = os.getenv("ICEBERG_NAMESPACE", "main")


def get_catalog():
    """
    Connect to Lakekeeper's Iceberg REST Catalog.
    """

    catalog = load_catalog(
        CATALOG_NAME,
        **{
            "type": "rest",
            "uri": LAKEKEEPER_URI,
            "warehouse": WAREHOUSE,

            # MinIO
            "s3.endpoint": os.getenv("S3_ENDPOINT", "http://localhost:9000"),
            "s3.access-key-id": os.getenv("MINIO_ROOT_USER", "lakehouse_admin"),
            "s3.secret-access-key": os.getenv("MINIO_ROOT_PASSWORD", "minIO123"),
            "s3.region": os.getenv("AWS_REGION", "us-east-1"),
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