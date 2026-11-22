import os
from pathlib import Path
import duckdb

PROJECT_DIR = Path(__file__).resolve().parent.parent
DUCKDB_PATH = str(PROJECT_DIR / "data" / "duckdb" / "tourism_lakehouse.duckdb")
EXPORT_DIR = PROJECT_DIR / "data" / "gold_export"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

con = duckdb.connect(DUCKDB_PATH, read_only=True)

tables = [
    "gold_obt_place_360_profile",
    "gold_fct_province_tourism_summary",
    "gold_fct_category_tourism_summary",
    "gold_fct_place_monthly_growth",
    "gold_fct_place_snapshot_trajectory",
    "gold_fct_youtube_video_performance",
]

print("=== EXPORTING GOLD TABLES TO PARQUET FOR POWER BI ===")
for tbl in tables:
    dest_path = (EXPORT_DIR / f"{tbl}.parquet").as_posix()
    con.execute(f"COPY (SELECT * FROM main.{tbl}) TO '{dest_path}' (FORMAT PARQUET);")
    count = con.execute(f"SELECT count(*) FROM main.{tbl}").fetchone()[0]
    print(f"Exported {tbl}: {count:,} rows -> {dest_path}")

con.close()
print("=== COMPLETED EXPORT ===")
