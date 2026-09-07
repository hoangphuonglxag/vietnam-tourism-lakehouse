import duckdb

from pyiceberg.catalog import load_catalog
import os

# =========================================================
# Configuration
# =========================================================

DUCKDB_PATH = "/tmp/tourism_lakehouse.duckdb"

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
# Lakekeeper
# =========================================================

def get_catalog():

    return load_catalog(
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
# Read dbt result from DuckDB
# =========================================================

def read_from_duckdb():

    print()
    print("========================================")
    print("Reading dbt result from DuckDB")
    print("========================================")

    con = duckdb.connect(DUCKDB_PATH)

    try:

        result = con.execute(
            """
            SELECT
                place_id,
                place_name,
                rating,
                review_text_cleaned,
                source
            FROM main.stg_travel_reviews
            """
        )

        arrow_table = result.fetch_arrow_table()

        print(f"Rows read: {arrow_table.num_rows}")
        print(f"Columns: {arrow_table.column_names}")

        return arrow_table

    finally:

        con.close()


# =========================================================
# Write to Iceberg
# =========================================================

def write_to_iceberg(arrow_table):

    print()
    print("========================================")
    print("Writing to Iceberg")
    print("========================================")

    catalog = get_catalog()

    identifier = f"{NAMESPACE}.{TABLE_NAME}"

    # -----------------------------------------------------
    # Namespace
    # -----------------------------------------------------

    if not catalog.namespace_exists(NAMESPACE):

        print(f"Creating namespace: {NAMESPACE}")

        catalog.create_namespace(NAMESPACE)

    # -----------------------------------------------------
    # Table
    # -----------------------------------------------------

    if catalog.table_exists(identifier):

        print(f"Iceberg table already exists: {identifier}")

        table = catalog.load_table(identifier)

    else:

        print(f"Creating Iceberg table: {identifier}")

        table = catalog.create_table(
            identifier,
            schema=arrow_table.schema,
        )

        print("Iceberg table created.")

    # -----------------------------------------------------
    # Append
    # -----------------------------------------------------

    print()
    print("Appending Arrow data...")

    table.append(arrow_table)

    print("Append successful.")

    print()
    print("========================================")
    print("Iceberg write completed")
    print("========================================")

    print(f"Table    : {identifier}")
    print(f"Location : {table.location()}")
    print(f"Rows     : {arrow_table.num_rows}")


# =========================================================
# Main
# =========================================================

def main():

    print()
    print("========================================")
    print("TOURISM LAKEHOUSE")
    print("DBT → DUCKDB → PYARROW → PYICEBERG")
    print("========================================")

    arrow_table = read_from_duckdb()

    if arrow_table.num_rows == 0:

        raise RuntimeError(
            "DuckDB returned 0 rows. "
            "Iceberg write was cancelled."
        )

    write_to_iceberg(arrow_table)


if __name__ == "__main__":
    main()