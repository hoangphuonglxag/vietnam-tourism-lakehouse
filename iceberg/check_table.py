import argparse
import os
import sys
from pathlib import Path

import duckdb

# Cho phép chạy trực tiếp `python iceberg/check_table.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iceberg.catalog import get_catalog, get_layer_config


DEFAULT_DUCKDB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "duckdb" / "tourism_lakehouse.duckdb")
DUCKDB_PATH = os.getenv("DUCKDB_PATH", DEFAULT_DUCKDB_PATH)
DUCKDB_SCHEMA = os.getenv("DUCKDB_SCHEMA", "main")


def validate_layer(con: duckdb.DuckDBPyConnection, layer: str) -> None:
    cfg = get_layer_config(layer)
    namespace = cfg["namespace"]
    tables = cfg["tables"]
    catalog = get_catalog(layer)

    print()
    print("========================================")
    print(f"VALIDATE {layer.upper()} ICEBERG TABLES")
    print("========================================")

    for table_name in tables:
        identifier = f"{namespace}.{table_name}"
        print()
        print("----------------------------------------")
        print(f"Table: {identifier}")
        print("----------------------------------------")

        if not catalog.table_exists(identifier):
            raise RuntimeError(f"Iceberg table does not exist: {identifier}")

        table = catalog.load_table(identifier)
        snapshot = table.current_snapshot()
        if snapshot is None:
            raise RuntimeError(f"No snapshot found for Iceberg table: {identifier}")

        iceberg_rows = table.scan().to_arrow().num_rows
        duckdb_rows = con.execute(
            f"SELECT COUNT(*) FROM {DUCKDB_SCHEMA}.{table_name}"
        ).fetchone()[0]

        print(f"  Location    : {table.location()}")
        print(f"  Snapshot ID : {snapshot.snapshot_id}")
        print(f"  DuckDB rows : {duckdb_rows:,}")
        print(f"  Iceberg rows: {iceberg_rows:,}")

        if iceberg_rows != duckdb_rows or iceberg_rows == 0:
            raise RuntimeError(
                f"Row count mismatch for {identifier}: "
                f"DuckDB={duckdb_rows}, Iceberg={iceberg_rows}"
            )

        print("  Status      : PASS")

    print()
    print("========================================")
    print(f"PASS: All {len(tables)} {layer.capitalize()} Iceberg tables validated on MinIO!")
    print("========================================")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Apache Iceberg tables against DuckDB")
    parser.add_argument(
        "--layer",
        choices=["silver", "gold", "all"],
        default="silver",
        help="Medallion layer to validate (default: silver)",
    )
    args = parser.parse_args()

    layers = ["silver", "gold"] if args.layer == "all" else [args.layer]

    con = duckdb.connect(DUCKDB_PATH, read_only=True)
    try:
        for layer in layers:
            validate_layer(con, layer)
    finally:
        con.close()


if __name__ == "__main__":
    main()
