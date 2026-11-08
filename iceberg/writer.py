import os
import sys
from pathlib import Path

import duckdb

# Cho phép chạy trực tiếp `python iceberg/writer.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iceberg.catalog import NAMESPACE, SILVER_TABLES, get_catalog


DUCKDB_PATH = os.getenv("DUCKDB_PATH", "/tmp/tourism_lakehouse.duckdb")
DUCKDB_SCHEMA = os.getenv("DUCKDB_SCHEMA", "main")


def read_table_from_duckdb(con: duckdb.DuckDBPyConnection, table_name: str):
    """Read a Silver table from DuckDB as a PyArrow Table."""
    arrow_table = con.sql(f"SELECT * FROM {DUCKDB_SCHEMA}.{table_name}").to_arrow_table()
    return arrow_table


def write_table_to_iceberg(catalog, table_name: str, arrow_table) -> None:
    """Create or overwrite an Iceberg table in Lakekeeper / MinIO."""
    identifier = f"{NAMESPACE}.{table_name}"

    if not catalog.namespace_exists(NAMESPACE):
        print(f"Creating namespace: {NAMESPACE}")
        catalog.create_namespace(NAMESPACE)

    if catalog.table_exists(identifier):
        table = catalog.load_table(identifier)
        existing_cols = [field.name for field in table.schema().fields]
        if existing_cols != list(arrow_table.column_names):
            print(f"Schema changed for {identifier}; recreating Iceberg table...")
            catalog.purge_table(identifier)
            table = catalog.create_table(
                identifier,
                schema=arrow_table.schema,
            )
        else:
            print(f"Overwriting existing Iceberg table: {identifier}")
    else:
        print(f"Creating Iceberg table: {identifier}")
        table = catalog.create_table(
            identifier,
            schema=arrow_table.schema,
        )

    table.overwrite(arrow_table)

    print(f"  -> Location : {table.location()}")
    print(f"  -> Rows     : {arrow_table.num_rows:,}")
    print(f"  -> Columns  : {len(arrow_table.column_names)}")


def main() -> None:
    print()
    print("========================================")
    print("TOURISM LAKEHOUSE - SILVER TO ICEBERG")
    print("DBT -> DUCKDB -> PYARROW -> PYICEBERG -> MINIO")
    print("========================================")

    catalog = get_catalog()
    con = duckdb.connect(DUCKDB_PATH, read_only=True)

    try:
        for table_name in SILVER_TABLES:
            print()
            print(f"----------------------------------------")
            print(f"Syncing table: {table_name}")
            print(f"----------------------------------------")
            arrow_table = read_table_from_duckdb(con, table_name)
            if arrow_table.num_rows == 0:
                raise RuntimeError(
                    f"DuckDB table {DUCKDB_SCHEMA}.{table_name} returned 0 rows. "
                    "Iceberg write was cancelled."
                )
            write_table_to_iceberg(catalog, table_name, arrow_table)
    finally:
        con.close()

    print()
    print("========================================")
    print(f"All {len(SILVER_TABLES)} Silver tables written to Iceberg successfully!")
    print("========================================")


if __name__ == "__main__":
    main()
