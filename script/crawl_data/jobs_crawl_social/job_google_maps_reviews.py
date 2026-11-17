from __future__ import annotations

import csv
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pandas as pd
from playwright.sync_api import sync_playwright

from ..config import GOOGLE_MAPS_REVIEWS_FILE, PLACES_FILE, ensure_data_directories, env_bool, env_float, env_int
from ..crawl_social.crawl_google_reviews import GoogleMapsReviewsCrawler, Place
from ..utils.ingestion_storage import BronzeWriter, CheckpointStore, new_run_id
from ..metrics.ingestion import RunMetrics
from ..utils.crawl_plan import load_crawl_plan, run_context
from ...alerts.discord import crawl_progress


REVIEW_COLUMNS = [
    "review_id", "place_id", "rating", "review_text", "review_date",
    "likes_count", "source", "crawled_at_utc",
]
REVIEW_STATUS_FIELDS = [
    "place_id",
    "place_name",
    "province_name",
    "status",
    "requested_reviews",
    "loaded_reviews",
    "google_review_count",
    "error_message",
    "crawled_at",
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
    run_id = new_run_id("google_maps")
    plan = load_crawl_plan()
    context = run_context(plan, "google_reviews")
    checkpoint = CheckpointStore("google_maps/reviews", run_id=run_id, metadata=context)
    metrics = RunMetrics("google_maps_reviews", run_id, context)
    decision = plan["decisions"].get("reviews", {}) if plan else {}
    if plan and not decision.get("should_run"):
        metrics.finish("skipped")
        return
    data = pd.read_csv(PLACES_FILE, dtype=str, encoding="utf-8-sig").fillna("")
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
    if plan:
        target_ids = set(map(str, decision.get("place_ids", [])))
        data = data[data["place_id"].astype(str).isin(target_ids)]
    elif not refresh_success:
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
    if data.empty:
        metrics.finish("skipped")
        return
    bronze = BronzeWriter("google_maps/reviews", "google_maps", run_id=run_id, crawler_version="google-maps-review-1")

    concurrency = max(1, env_int("GOOGLE_MAPS_REVIEWS_CONCURRENCY", 3))
    concurrency = min(concurrency, len(data))
    lock = threading.Lock()
    is_stopped = False
    sync_csv = env_bool("TLCN_EXPORT_HISTORICAL_CSV", True)

    def stop_handler(signum: int, frame: object) -> None:
        nonlocal is_stopped
        is_stopped = True
        with lock:
            report = metrics.finish("stopped")
            crawl_progress("google_maps_reviews", report, remaining, stopped=True)
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, stop_handler)

    def process_place(crawler: GoogleMapsReviewsCrawler, row: dict[str, Any]) -> None:
        nonlocal remaining
        if is_stopped:
            return
        if not row.get("place_id"):
            with lock:
                metrics.mark("skipped")
            return
        if not plan and not refresh_success and checkpoint.is_fresh(
            str(row["place_id"]),
            int(row.get("crawl_interval_days") or 30),
        ):
            with lock:
                metrics.mark("skipped")
            return

        place = Place(
            place_id=str(row["place_id"]),
            place_name=str(row.get("place_name") or row.get("name_vi") or row.get("name_en") or ""),
            province_name=str(row.get("province_name", "")),
            latitude=str(row.get("latitude", "")),
            longitude=str(row.get("longitude", "")),
        )
        target_limit = None
        if plan:
            decision_item = decision.get("items_map", {}).get(str(row["place_id"]), {})
            target_limit = decision_item.get("max_reviews")
        if not target_limit and row.get("max_reviews"):
            try:
                target_limit = int(row["max_reviews"])
            except ValueError:
                pass

        try:
            reviews = crawler.crawl_place(
                place,
                max_count=target_limit,
                existing_ids=existing_ids if not refresh_success else None,
            )
            error = None
        except Exception as error_obj:
            reviews = []
            error = error_obj

        with lock:
            if error is not None:
                checkpoint.mark(place.place_id, type(error).__name__, error_message=str(error))
                metrics.mark("failed")
                print(f"[ERROR] place_id={place.place_id}: {error}", flush=True)
            else:
                new_reviews = _append(reviews, existing_ids) if sync_csv else len(reviews)
                metrics.add("reviews_found", len(reviews))
                metrics.add("new_reviews", new_reviews)
                bronze.write([review.__dict__ for review in reviews], source_id=place.place_id)
                if not reviews:
                    metrics.add("empty_reviews", 1)
                    checkpoint.mark(place.place_id, "EMPTY")
                    metrics.mark("empty")
                else:
                    checkpoint.mark(place.place_id, "SUCCESS")
                    metrics.mark("success")

            remaining -= 1
            report = metrics.write()
            crawl_progress("google_maps_reviews", report, remaining)

    def worker_thread(worker_id: int, worker_rows: list[dict[str, Any]]) -> None:
        if not worker_rows or is_stopped:
            return
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(locale="vi-VN", timezone_id="Asia/Ho_Chi_Minh")
            crawler = GoogleMapsReviewsCrawler(context)
            try:
                for row in worker_rows:
                    if is_stopped:
                        break
                    process_place(crawler, row)
                    time.sleep(delay_seconds)
            finally:
                crawler.close()
                browser.close()

    records = data.to_dict("records")
    batches: list[list[dict[str, Any]]] = [[] for _ in range(concurrency)]
    for i, record in enumerate(records):
        batches[i % concurrency].append(record)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(worker_thread, idx + 1, batch)
            for idx, batch in enumerate(batches)
            if batch
        ]
        for future in futures:
            future.result()
    report = metrics.finish()
    if env_bool("GOOGLE_MAPS_REVIEWS_REQUIRE_DATA", False):
        if report["reviews_found"] == 0:
            raise RuntimeError("Review smoke test found no reviews")
    failed_count = int(report.get("failed", 0))
    success_count = int(report.get("success", 0))
    empty_count = int(report.get("empty", 0))
    valid_count = success_count + empty_count
    if failed_count > 0 and valid_count == 0:
        raise RuntimeError(f"Google Maps reviews failed completely: {failed_count} failed places and 0 succeeded")
    elif failed_count > 0:
        print(
            f"[WARNING] Google Maps reviews had {failed_count} failed places out of {report.get('total', 0)} "
            f"(success: {success_count}, empty: {empty_count}). Continuing downstream.",
            flush=True,
        )


if __name__ == "__main__":
    run()