from __future__ import annotations

import csv
import signal
import time
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

from ..config import GOOGLE_MAPS_ERRORS_FILE, GOOGLE_MAPS_RATINGS_FILE, PLACES_FILE, ensure_data_directories, env_bool, env_float, env_int
from ..crawlers.google_maps.rating import crawl_place
from ..ingestion import BronzeWriter, CheckpointStore, new_run_id
from ..metrics.ingestion import RunMetrics
from ..region_priority import filter_places
from ..alerts.discord import crawl_progress


RATING_COLUMNS = [
    "place_id", "place_name", "province_id", "province_name", "google_maps_url",
    "google_rating", "google_review_count", "rating_5_count", "rating_4_count",
    "rating_3_count", "rating_2_count", "rating_1_count", "crawl_status",
    "error_message", "crawled_at",
]
ERROR_COLUMNS = ["place_id", "place_name", "province_id", "province_name", "error_type", "error_message", "failed_at"]


def _append(row: dict[str, object], target: Path, columns: list[str]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    new_file = not target.exists()
    with target.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        if new_file:
            writer.writeheader()
        writer.writerow({column: row.get(column, "") for column in columns})


def _successful_places(target: Path) -> set[str]:
    if not target.exists():
        return set()
    data = pd.read_csv(target, dtype=str, encoding="utf-8-sig")
    if "place_id" not in data or "crawl_status" not in data:
        return set()
    return set(data.loc[data["crawl_status"] == "success", "place_id"].dropna())


def run() -> None:
    ensure_data_directories()
    run_id = new_run_id("google_maps")
    bronze_ratings = BronzeWriter("google_maps/ratings", "google_maps", run_id=run_id, crawler_version="google-maps-rating-1")
    bronze_errors = BronzeWriter("google_maps/errors", "google_maps", run_id=run_id, crawler_version="google-maps-rating-1")
    checkpoint = CheckpointStore("google_maps/ratings")
    places = pd.read_csv(PLACES_FILE, dtype=str, encoding="utf-8-sig").fillna("").to_dict("records")
    places = filter_places(pd.DataFrame(places)).to_dict("records")
    refresh_success = env_bool("TLCN_REFRESH_SUCCESS", False)
    delay_seconds = env_float("GOOGLE_MAPS_DELAY_SECONDS", 1.0)
    metrics = RunMetrics("google_maps_ratings", run_id)
    completed = _successful_places(GOOGLE_MAPS_RATINGS_FILE)
    limit = env_int("GOOGLE_MAPS_RATINGS_LIMIT", 0)
    if not refresh_success:
        places = [place for place in places if str(place.get("place_id", "")) not in completed and not checkpoint.is_success(str(place.get("place_id", "")))]
    if limit > 0:
        places = places[:limit]
    remaining = len(places)

    def stop_handler(signum: int, frame: object) -> None:
        report = metrics.write()
        crawl_progress("google_maps_ratings", report, remaining, stopped=True)
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, stop_handler)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=env_bool("HEADLESS", True))
        page = browser.new_page(locale="vi-VN")
        try:
            for place in places:
                place_id = str(place.get("place_id", ""))
                if not place_id:
                    metrics.mark("skipped")
                    continue
                if not refresh_success and (place_id in completed or checkpoint.is_success(place_id)):
                    metrics.mark("skipped")
                    continue
                base = {
                    "place_id": place_id, "place_name": place.get("place_name", ""),
                    "province_id": place.get("province_id", ""), "province_name": place.get("province_name", ""),
                    "google_maps_url": place.get("google_maps_url", ""),
                    "rating_5_count": 0, "rating_4_count": 0, "rating_3_count": 0,
                    "rating_2_count": 0, "rating_1_count": 0,
                }
                try:
                    result = crawl_place(page, place)
                    output = {**base, **result, "crawl_status": "success", "error_message": ""}
                    _append(output, GOOGLE_MAPS_RATINGS_FILE, RATING_COLUMNS)
                    bronze_ratings.write([output], source_id=place_id, source_url=str(output.get("google_maps_url", "")))
                    checkpoint.mark(place_id, "SUCCESS")
                    completed.add(place_id)
                    metrics.mark("success")
                except Exception as error:
                    failure = {**base, "error_type": type(error).__name__, "error_message": str(error),
                               "failed_at": pd.Timestamp.utcnow().isoformat()}
                    _append(failure, GOOGLE_MAPS_ERRORS_FILE, ERROR_COLUMNS)
                    bronze_errors.write([failure], source_id=place_id, source_url=str(base.get("google_maps_url", "")))
                    checkpoint.mark(place_id, "FAILED", error_message=str(error))
                    metrics.mark("failed")
                remaining -= 1
                report = metrics.write()
                crawl_progress("google_maps_ratings", report, remaining)
                time.sleep(delay_seconds)
        finally:
            browser.close()
    report = metrics.write()
    if report["failed"]:
        raise RuntimeError(f"Google Maps ratings had {report['failed']} failed places")


if __name__ == "__main__":
    run()