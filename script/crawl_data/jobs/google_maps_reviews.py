from __future__ import annotations

import csv
import os
import signal
import time

import pandas as pd
from playwright.sync_api import sync_playwright

from ..config import GOOGLE_MAPS_REVIEWS_FILE, PLACES_FILE, ensure_data_directories, env_bool, env_float, env_int
from ..crawlers.google_maps.reviews import GoogleMapsReviewsCrawler, Place
from ..ingestion import BronzeWriter, CheckpointStore, new_run_id
from ..metrics.ingestion import RunMetrics
from ..region_priority import filter_places
from ..alerts.discord import crawl_progress


REVIEW_COLUMNS = [
    "review_id", "place_id", "rating", "review_text", "review_date",
    "likes_count", "source", "crawled_at_utc",
]


def _existing_ids() -> set[str]:
    if not GOOGLE_MAPS_REVIEWS_FILE.exists():
        return set()
    data = pd.read_csv(
        GOOGLE_MAPS_REVIEWS_FILE,
        dtype=str,
        encoding="utf-8-sig",
        on_bad_lines="skip",
    )
    return set(data.get("review_id", pd.Series(dtype=str)).dropna())


def _append(reviews: list[object], existing_ids: set[str]) -> int:
    new_reviews = [review for review in reviews if review.review_id not in existing_ids]
    if not new_reviews:
        return 0
    GOOGLE_MAPS_REVIEWS_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_file = not GOOGLE_MAPS_REVIEWS_FILE.exists()
    with GOOGLE_MAPS_REVIEWS_FILE.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=REVIEW_COLUMNS)
        if new_file:
            writer.writeheader()
        for review in new_reviews:
            writer.writerow({field: getattr(review, field) for field in REVIEW_COLUMNS})
            existing_ids.add(review.review_id)
    return len(new_reviews)


def run() -> None:
    ensure_data_directories()
    bronze = BronzeWriter("google_maps/reviews", "google_maps", run_id=new_run_id("google_maps"), crawler_version="google-maps-review-1")
    run_id = bronze.run_id
    checkpoint = CheckpointStore("google_maps/reviews")
    data = pd.read_csv(PLACES_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    data = filter_places(data)
    existing_ids = _existing_ids()
    headless = env_bool("HEADLESS", False)
    delay_seconds = env_float("GOOGLE_MAPS_REVIEWS_DELAY_SECONDS", 1.0)
    refresh_success = env_bool("TLCN_REFRESH_SUCCESS", False)
    metrics = RunMetrics("google_maps_reviews", run_id)
    if not refresh_success:
        data = data[~data["place_id"].astype(str).map(checkpoint.is_success)]
    limit = env_int("GOOGLE_MAPS_REVIEWS_LIMIT", 0)
    if limit > 0:
        data = data.head(limit)
    remaining = len(data)

    def stop_handler(signum: int, frame: object) -> None:
        report = metrics.write()
        crawl_progress("google_maps_reviews", report, remaining, stopped=True)
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, stop_handler)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(locale="vi-VN", timezone_id="Asia/Ho_Chi_Minh")
        crawler = GoogleMapsReviewsCrawler(context)
        try:
            for row in data.to_dict("records"):
                if not row.get("place_id"):
                    metrics.mark("skipped")
                    continue
                if not refresh_success and checkpoint.is_success(str(row["place_id"])):
                    metrics.mark("skipped")
                    continue
                place = Place(
                    place_id=str(row["place_id"]),
                    place_name=str(row.get("place_name") or row.get("name_vi") or row.get("name_en") or ""),
                    province_name=str(row.get("province_name", "")),
                    latitude=str(row.get("latitude", "")),
                    longitude=str(row.get("longitude", "")),
                )
                try:
                    reviews = crawler.crawl_place(place)
                    _append(reviews, existing_ids)
                    bronze.write([review.__dict__ for review in reviews], source_id=place.place_id)
                    checkpoint.mark(place.place_id, "SUCCESS")
                    metrics.mark("success")
                except Exception as error:
                    checkpoint.mark(place.place_id, "FAILED", error_message=str(error))
                    metrics.mark("failed")
                    print(f"[ERROR] place_id={place.place_id}: {error}", flush=True)
                remaining -= 1
                report = metrics.write()
                crawl_progress("google_maps_reviews", report, remaining)
                time.sleep(delay_seconds)
        finally:
            crawler.close()
            browser.close()
    report = metrics.write()
    if report["failed"]:
        raise RuntimeError(f"Google Maps reviews had {report['failed']} failed places")


if __name__ == "__main__":
    run()