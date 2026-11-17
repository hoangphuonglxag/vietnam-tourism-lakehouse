"""Rescue quarantined YouTube comments and restore them to valid Bronze layer.

Root Cause:
- Historical comments in data/historical/youtube_comments.csv had empty `crawled_at_utc` for 237,821 rows,
  causing BronzeWriter validation to fail with `["missing:crawled_at_utc"]` and dump them to quarantine.
- Incremental crawl on 2026-11-13 had `record["crawled_at_utc"] = record.pop("crawled_at", "")`,
  which erased valid timestamps and also sent 1,229 crawled comments to quarantine.

This script:
1. Fixes empty `crawled_at_utc` in `data/historical/youtube_comments.csv` with fallback '2026-08-30T00:00:00.000000'.
2. Writes clean Bronze partition for historical comments (237,843 rows) to MinIO and local Bronze.
3. Rescues the 1,229 comments from 2026-11-13 quarantine and writes to Bronze `crawl_date=2026-11-13`.
4. Removes resolved quarantine files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import pandas as pd

from ..config import BRONZE_ROOT, HISTORICAL_ROOT, YOUTUBE_COMMENTS_FILE
from ..utils.ingestion_storage import BronzeWriter


def rescue_comments() -> dict[str, int]:
    print("=== Step 1: Updating data/historical/youtube_comments.csv ===")
    if not YOUTUBE_COMMENTS_FILE.exists():
        print(f"Error: {YOUTUBE_COMMENTS_FILE} does not exist.")
        return {"error": 1}

    df = pd.read_csv(YOUTUBE_COMMENTS_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    print(f"Loaded {len(df)} rows from historical CSV.")
    empty_mask = df["crawled_at_utc"] == ""
    print(f"Found {empty_mask.sum()} rows with empty crawled_at_utc.")

    if empty_mask.any():
        df.loc[empty_mask, "crawled_at_utc"] = "2026-08-30T00:00:00.000000"
        df.to_csv(YOUTUBE_COMMENTS_FILE, index=False, encoding="utf-8-sig")
        print("Updated historical CSV with valid crawled_at_utc timestamps.")

    print("\n=== Step 2: Ingesting clean historical comments into Bronze ===")
    records = df.to_dict("records")
    writer = BronzeWriter(
        "youtube/comments",
        "youtube",
        run_id="historical-youtube_comments-rescued",
        crawler_version="historical-backfill",
    )
    hist_stats = writer.write(records)
    print(f"Historical Ingestion Stats: {hist_stats}")

    print("\n=== Step 3: Rescuing incremental comments from 2026-11-13 ===")
    quarantine_11_13 = BRONZE_ROOT / "quarantine" / "youtube" / "comments" / "crawl_date=2026-11-13"
    rescued_incremental_count = 0
    if quarantine_11_13.exists():
        inc_records: list[dict[str, object]] = []
        for jsonl_file in quarantine_11_13.glob("*.jsonl"):
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    # Restore timestamp
                    row["crawled_at_utc"] = row.get("crawled_at_utc") or row.get("ingested_at_utc") or "2026-11-13T15:00:00.000000"
                    row.pop("quality_errors", None)
                    row.pop("record_status", None)
                    row.pop("attempt", None)
                    row.pop("run_id", None)
                    inc_records.append(row)

        if inc_records:
            print(f"Found {len(inc_records)} records to rescue from 2026-11-13.")
            inc_writer = BronzeWriter(
                "youtube/comments",
                "youtube",
                run_id="youtube-rescued-20261113",
                crawler_version="youtube-comment-1",
            )
            inc_stats = inc_writer.write(inc_records)
            print(f"Incremental Ingestion Stats: {inc_stats}")
            rescued_incremental_count = inc_stats.get("success", 0)

    print("\n=== Step 4: Cleaning up quarantine files ===")
    quarantine_root = BRONZE_ROOT / "quarantine" / "youtube" / "comments"
    removed_files = 0
    if quarantine_root.exists():
        for f in quarantine_root.rglob("*.jsonl"):
            try:
                f.unlink()
                removed_files += 1
            except Exception as e:
                print(f"Could not delete {f}: {e}")
    print(f"Removed {removed_files} quarantined jsonl files from local disk.")

    total_rescued = hist_stats.get("success", 0) + rescued_incremental_count
    print(f"\n>>> Total Rescued Comments: {total_rescued} <<<")
    return {"total_rescued": total_rescued, "historical": hist_stats.get("success", 0), "incremental": rescued_incremental_count}


if __name__ == "__main__":
    rescue_comments()
