import os
import sys
from pathlib import Path

import duckdb

# Cho phép chạy trực tiếp `python iceberg/check_table.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iceberg.catalog import NAMESPACE, SILVER_TABLES, get_catalog


DUCKDB_PATH = os.getenv("DUCKDB_PATH", "/tmp/tourism_lakehouse.duckdb")
DUCKDB_SCHEMA = os.getenv("DUCKDB_SCHEMA", "main")


def main() -> None:
    print()
    print("========================================")
    print("VALIDATE SILVER ICEBERG TABLES")
    print("========================================")

    catalog = get_catalog()
    con = duckdb.connect(DUCKDB_PATH, read_only=True)

    try:
        for table_name in SILVER_TABLES:
            identifier = f"{NAMESPACE}.{table_name}"
            print()
            print(f"----------------------------------------")
            print(f"Table: {identifier}")
            print(f"----------------------------------------")

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

            print(f"  Status      : PASS")
    finally:
        con.close()

    print()
    print("========================================")
    print(f"PASS: All {len(SILVER_TABLES)} Silver Iceberg tables validated on MinIO!")
    print("========================================")


if __name__ == "__main__":
    main()
