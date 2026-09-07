from pyiceberg.catalog import load_catalog
import os

# =========================================================
# Configuration
# =========================================================
LAKEKEEPER_URI = os.getenv(
    "LAKEKEEPER_URI",
    "http://localhost:8181/catalog",
)

WAREHOUSE = "tourism_warehouse"

NAMESPACE = "main"

TABLE_NAME = "stg_travel_reviews"


S3_ENDPOINT = os.getenv(
    "S3_ENDPOINT",
    "http://localhost:9000",
)

S3_ACCESS_KEY = os.getenv(
    "MINIO_ROOT_USER",
    "lakehouse_admin",
)

S3_SECRET_KEY = os.getenv(
    "MINIO_ROOT_PASSWORD",
    "minIO123",
)

S3_REGION = os.getenv(
    "AWS_REGION",
    "us-east-1",
)

# =========================================================
# Connect to Lakekeeper
# =========================================================

catalog = load_catalog(
    "lakekeeper",
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


# =========================================================
# Load Iceberg table
# =========================================================

identifier = f"{NAMESPACE}.{TABLE_NAME}"

print()
print("========================================")
print("CHECK ICEBERG TABLE")
print("========================================")

print(f"Table: {identifier}")

if not catalog.table_exists(identifier):
    raise RuntimeError(
        f"Iceberg table does not exist: {identifier}"
    )


table = catalog.load_table(identifier)

print()
print("Table loaded successfully.")

print()
print("Location:")
print(table.location())


# =========================================================
# Schema
# =========================================================

print()
print("========================================")
print("SCHEMA")
print("========================================")

print(table.schema())


# =========================================================
# Current snapshot
# =========================================================

print()
print("========================================")
print("CURRENT SNAPSHOT")
print("========================================")

snapshot = table.current_snapshot()

if snapshot is None:

    print("No snapshot found.")

else:

    print(f"Snapshot ID: {snapshot.snapshot_id}")
    print(f"Timestamp  : {snapshot.timestamp_ms}")


# =========================================================
# Scan data
# =========================================================

print()
print("========================================")
print("READ DATA FROM ICEBERG")
print("========================================")

arrow_table = table.scan().to_arrow()

print(f"Rows: {arrow_table.num_rows}")

print()
print("Columns:")
print(arrow_table.column_names)

print()
print("Data:")

print(arrow_table.to_pydict())


# =========================================================
# Final result
# =========================================================

print()
print("========================================")

if arrow_table.num_rows == 3:

    print("PASS: Iceberg contains 3 rows.")

else:

    print(
        f"WARNING: Expected 3 rows, "
        f"but found {arrow_table.num_rows}."
    )

print("========================================")