from __future__ import annotations

import json

import pandas as pd

from .config import BRONZE_ROOT, HISTORICAL_ROOT, ensure_data_directories
from .ingestion import BronzeWriter


DATASETS = {
    "google_maps_ratings.csv": ("google_maps/ratings", "google_maps"),
    "google_maps_reviews.csv": ("google_maps/reviews", "google_maps"),
    "google_maps_errors.csv": ("google_maps/errors", "google_maps"),
    "youtube_videos.csv": ("youtube/videos", "youtube"),
    "youtube_comments.csv": ("youtube/comments", "youtube"),
    "youtube_crawl_log.csv": ("youtube/crawl_log", "youtube"),
    "youtube_comments_crawl_log.csv": ("youtube/comments_crawl_log", "youtube"),
}


def _normalise_columns(data: pd.DataFrame, dataset: str) -> pd.DataFrame:
    if dataset in {"google_maps/reviews", "youtube/comments"} and "crawled_at_utc" not in data:
        if "crawled_at" in data:
            data = data.rename(columns={"crawled_at": "crawled_at_utc"})
    return data


def backfill(force: bool = False) -> dict[str, dict[str, int]]:
    ensure_data_directories()
    results: dict[str, dict[str, int]] = {}
    manifest_dir = BRONZE_ROOT / "_backfill"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    for filename, (dataset, source) in DATASETS.items():
        input_file = HISTORICAL_ROOT / filename
        marker = manifest_dir / f"{filename}.json"
        if not input_file.exists():
            continue
        if marker.exists() and not force:
            results[filename] = {"skipped": 1}
            continue
        data = pd.read_csv(input_file, dtype=str, encoding="utf-8-sig").fillna("")
        data = _normalise_columns(data, dataset)
        stats = BronzeWriter(dataset, source, run_id=f"historical-{input_file.stem}", crawler_version="historical-backfill").write(data.to_dict("records"))
        marker.write_text(json.dumps({"file": str(input_file), "rows": len(data), "stats": stats}), encoding="utf-8")
        results[filename] = stats
    return results


if __name__ == "__main__":
    print(json.dumps(backfill(), indent=2))