from __future__ import annotations

import csv
import os
import signal
import time

import pandas as pd
from playwright.sync_api import sync_playwright

from ..config import GOOGLE_MAPS_REVIEWS_FILE, PLACES_FILE, ensure_data_directories, env_bool, env_float, env_int
from ..crawlers.google_maps.reviews import GoogleMapsReviewsCrawler, Place
from ..utils.ingestion import BronzeWriter, CheckpointStore, new_run_id
from ..metrics.ingestion import RunMetrics
from ..utils.region_priority import filter_places
from ..alerts.discord import crawl_progress
from ..utils.status import SUCCESS, classify_error


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
        engine="python",
    )
    return set(data.get("review_id", pd.Series(dtype=str)).dropna())


# def _append(reviews: list[object], existing_ids: set[str]) -> int:
#     new_reviews = [review for review in reviews if review.review_id not in existing_ids]
#     if not new_reviews:
#         return 0
#     GOOGLE_MAPS_REVIEWS_FILE.parent.mkdir(parents=True, exist_ok=True)
#     new_file = not GOOGLE_MAPS_REVIEWS_FILE.exists()
#     with GOOGLE_MAPS_REVIEWS_FILE.open("a", encoding="utf-8-sig", newline="") as file:
#         writer = csv.DictWriter(file, fieldnames=REVIEW_COLUMNS)
#         if new_file:
#             writer.writeheader()
#         for review in new_reviews:
#             writer.writerow({field: getattr(review, field) for field in REVIEW_COLUMNS})
#             existing_ids.add(review.review_id)
#     return len(new_reviews)

def _append(reviews: list[object], existing_ids: set[str]) -> int:
    new_reviews = []
    batch_ids = set()

    for review in reviews:
        review_id = getattr(review, "review_id", None)

        if not review_id:
            continue

        if review_id in existing_ids:
            continue

        if review_id in batch_ids:
            continue

        new_reviews.append(review)
        batch_ids.add(review_id)

    if not new_reviews:
        return 0

    GOOGLE_MAPS_REVIEWS_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_file = not GOOGLE_MAPS_REVIEWS_FILE.exists()

    with GOOGLE_MAPS_REVIEWS_FILE.open(
        "a",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=REVIEW_COLUMNS)

        if new_file:
            writer.writeheader()

        for review in new_reviews:
            writer.writerow({
                field: getattr(review, field)
                for field in REVIEW_COLUMNS
            })
            existing_ids.add(review.review_id)

    return len(new_reviews)



def run() -> None:
    ensure_data_directories()
    bronze = BronzeWriter("google_maps/reviews", "google_maps", run_id=new_run_id("google_maps"), crawler_version="google-maps-review-1")
    run_id = bronze.run_id
    checkpoint = CheckpointStore("google_maps/reviews")
    data = pd.read_csv(PLACES_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    data = filter_places(data)
    requested_place_ids = {
        item.strip()
        for item in os.getenv("GOOGLE_MAPS_REVIEWS_PLACE_IDS", "").split(",")
        if item.strip()
    }
    if requested_place_ids:
        data = data[data["place_id"].astype(str).isin(requested_place_ids)]
    existing_ids = _existing_ids()
    headless = env_bool("HEADLESS", False)
    delay_seconds = env_float("GOOGLE_MAPS_REVIEWS_DELAY_SECONDS", 1.0)
    refresh_success = env_bool("TLCN_REFRESH_SUCCESS", False)
    metrics = RunMetrics("google_maps_reviews", run_id)
    if not refresh_success:
        data = data[
            ~data.apply(
                lambda row: checkpoint.is_fresh(
                    str(row["place_id"]),
                    int(row.get("crawl_interval_days") or 30),
                ),
                axis=1,
            )
        ]
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
                if not refresh_success and checkpoint.is_fresh(
                    str(row["place_id"]),
                    int(row.get("crawl_interval_days") or 30),
                ):
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
                    new_reviews = _append(reviews, existing_ids)
                    metrics.add("reviews_found", len(reviews))
                    metrics.add("new_reviews", new_reviews)
                    bronze.write([review.__dict__ for review in reviews], source_id=place.place_id)
                    if not reviews:
                        metrics.add("empty_reviews", 1)
                        checkpoint.mark(place.place_id, "EMPTY")
                        metrics.mark("empty")
                    else:
                        checkpoint.mark(place.place_id, SUCCESS)
                        metrics.mark("success")
                except Exception as error:
                    checkpoint.mark(place.place_id, classify_error(error), error_message=str(error))
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
    if env_bool("GOOGLE_MAPS_REVIEWS_REQUIRE_DATA", False):
        if report["reviews_found"] == 0:
            raise RuntimeError("Review smoke test found no reviews")
    if report["failed"]:
        raise RuntimeError(f"Google Maps reviews had {report['failed']} failed places")


if __name__ == "__main__":
    run()