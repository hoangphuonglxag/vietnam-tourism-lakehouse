import argparse
import os
import sys
from pathlib import Path

import duckdb

# Cho phép chạy trực tiếp `python iceberg/writer.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iceberg.catalog import get_catalog, get_layer_config


DEFAULT_DUCKDB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "duckdb" / "tourism_lakehouse.duckdb")
DUCKDB_PATH = os.getenv("DUCKDB_PATH", DEFAULT_DUCKDB_PATH)
DUCKDB_SCHEMA = os.getenv("DUCKDB_SCHEMA", "main")


def read_table_from_duckdb(con: duckdb.DuckDBPyConnection, table_name: str):
    """Read a table from DuckDB as a PyArrow Table."""
    arrow_table = con.sql(f"SELECT * FROM {DUCKDB_SCHEMA}.{table_name}").to_arrow_table()
    return arrow_table


def write_table_to_iceberg(catalog, namespace: str, table_name: str, arrow_table) -> None:
    """Create or overwrite an Iceberg table in Lakekeeper / MinIO."""
    identifier = f"{namespace}.{table_name}"

    if not catalog.namespace_exists(namespace):
        print(f"Creating namespace: {namespace}")
        catalog.create_namespace(namespace)

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


def sync_layer(con: duckdb.DuckDBPyConnection, layer: str) -> None:
    cfg = get_layer_config(layer)
    namespace = cfg["namespace"]
    tables = cfg["tables"]
    catalog = get_catalog(layer)

    print()
    print("========================================")
    print(f"TOURISM LAKEHOUSE - {layer.upper()} TO ICEBERG")
    print("DBT -> DUCKDB -> PYARROW -> PYICEBERG -> MINIO")
    print("========================================")

    for table_name in tables:
        print()
        print("----------------------------------------")
        print(f"Syncing table: {table_name}")
        print("----------------------------------------")
        arrow_table = read_table_from_duckdb(con, table_name)
        if arrow_table.num_rows == 0:
            raise RuntimeError(
                f"DuckDB table {DUCKDB_SCHEMA}.{table_name} returned 0 rows. "
                "Iceberg write was cancelled."
            )
        write_table_to_iceberg(catalog, namespace, table_name, arrow_table)

    print()
    print("========================================")
    print(f"All {len(tables)} {layer.capitalize()} tables written to Iceberg successfully!")
    print("========================================")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync DuckDB tables to Apache Iceberg on MinIO")
    parser.add_argument(
        "--layer",
        choices=["silver", "gold", "all"],
        default="silver",
        help="Medallion layer to sync (default: silver)",
    )
    args = parser.parse_args()

    layers = ["silver", "gold"] if args.layer == "all" else [args.layer]

    con = duckdb.connect(DUCKDB_PATH, read_only=True)
    try:
        for layer in layers:
            sync_layer(con, layer)
    finally:
        con.close()


if __name__ == "__main__":
    main()
