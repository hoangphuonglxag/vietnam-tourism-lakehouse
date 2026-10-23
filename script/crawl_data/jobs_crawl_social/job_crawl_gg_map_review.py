from __future__ import annotations

import csv
import os
import signal
import time
from pathlib import Path
from typing import Any

import pandas as pd
from playwright.sync_api import sync_playwright

from ..config import (
    GOOGLE_MAPS_REVIEWS_FILE,
    PLACES_FILE,
    ensure_data_directories,
    env_bool,
    env_float,
    env_int,
)
from ..crawl_social.crawl_google_reviews import GoogleMapsReviewsCrawler, Place
from ..utils.ingestion_storage import BronzeWriter, CheckpointStore, new_run_id
from ..metrics.ingestion import RunMetrics
from ..utils.crawl_plan import load_crawl_plan, run_context
from ...alerts.discord import crawl_progress


REVIEW_COLUMNS = [
    "review_id",
    "place_id",
    "rating",
    "review_text",
    "review_date",
    "likes_count",
    "source",
    "crawled_at_utc",
]


def _existing_ids() -> set[str]:
    if not GOOGLE_MAPS_REVIEWS_FILE.exists():
        return set()
    try:
        data = pd.read_csv(
            GOOGLE_MAPS_REVIEWS_FILE,
            dtype=str,
            encoding="utf-8-sig",
            on_bad_lines="skip",
            engine="python",
        )
    except (pd.errors.EmptyDataError, OSError):
        return set()
    if "review_id" not in data.columns:
        return set()
    return set(data["review_id"].dropna().astype(str).str.strip())


def _append(reviews: list[object], existing_ids: set[str]) -> int:
    """Append only new review IDs; preserve the existing CSV schema."""
    new_reviews: list[object] = []
    batch_ids: set[str] = set()
    for review in reviews:
        review_id = str(getattr(review, "review_id", "") or "").strip()
        if not review_id or review_id in existing_ids or review_id in batch_ids:
            continue
        new_reviews.append(review)
        batch_ids.add(review_id)
    if not new_reviews:
        return 0

    GOOGLE_MAPS_REVIEWS_FILE.parent.mkdir(parents=True, exist_ok=True)
    is_new_file = not GOOGLE_MAPS_REVIEWS_FILE.exists() or GOOGLE_MAPS_REVIEWS_FILE.stat().st_size == 0
    # utf-8-sig only for the initial file; avoid adding a BOM on every append.
    encoding = "utf-8-sig" if is_new_file else "utf-8"
    with GOOGLE_MAPS_REVIEWS_FILE.open("a", encoding=encoding, newline="") as file:
        writer = csv.DictWriter(file, fieldnames=REVIEW_COLUMNS, extrasaction="ignore")
        if is_new_file:
            writer.writeheader()
        for review in new_reviews:
            row = {field: getattr(review, field, None) for field in REVIEW_COLUMNS}
            writer.writerow(row)
            existing_ids.add(str(row["review_id"]))
    return len(new_reviews)


def _int_or_default(value: Any, default: int = 30) -> int:
    try:
        return int(str(value).strip()) if str(value).strip() else default
    except (TypeError, ValueError):
        return default


def _build_place(row: dict[str, Any]) -> Place:
    return Place(
        place_id=str(row.get("place_id", "")).strip(),
        place_name=str(row.get("place_name") or row.get("name_vi") or row.get("name_en") or "").strip(),
        province_name=str(row.get("province_name", "")).strip(),
        latitude=str(row.get("latitude", "")).strip(),
        longitude=str(row.get("longitude", "")).strip(),
    )


def run() -> None:
    ensure_data_directories()
    run_id = new_run_id("google_maps")
    plan = load_crawl_plan()
    context_info = run_context(plan, "google_reviews")
    checkpoint = CheckpointStore("google_maps/reviews", run_id=run_id, metadata=context_info)
    metrics = RunMetrics("google_maps_reviews", run_id, context_info)
    decision = plan["decisions"].get("reviews", {}) if plan else {}

    if plan and not decision.get("should_run"):
        metrics.finish("skipped")
        return

    if not PLACES_FILE.exists():
        metrics.finish("failed")
        raise FileNotFoundError(f"Không tìm thấy file places: {PLACES_FILE}")
    data = pd.read_csv(PLACES_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    if "place_id" not in data.columns:
        metrics.finish("failed")
        raise ValueError(f"File places thiếu cột place_id: {PLACES_FILE}")

    requested_place_ids = {
        item.strip()
        for item in os.getenv("GOOGLE_MAPS_REVIEWS_PLACE_IDS", "").split(",")
        if item.strip()
    }
    if requested_place_ids:
        data = data[data["place_id"].astype(str).isin(requested_place_ids)]

    headless = env_bool("HEADLESS", False)
    delay_seconds = max(0.0, env_float("GOOGLE_MAPS_REVIEWS_DELAY_SECONDS", 1.0))
    refresh_success = env_bool("TLCN_REFRESH_SUCCESS", False)

    if plan:
        target_ids = set(map(str, decision.get("place_ids", [])))
        data = data[data["place_id"].astype(str).isin(target_ids)]
    elif not refresh_success:
        data = data[
            ~data.apply(
                lambda row: checkpoint.is_fresh(
                    str(row["place_id"]),
                    _int_or_default(row.get("crawl_interval_days"), 30),
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

    bronze = BronzeWriter(
        "google_maps/reviews",
        "google_maps",
        run_id=run_id,
        crawler_version="google-maps-review-2",
    )

    def stop_handler(signum: int, frame: Any) -> None:
        report = metrics.finish("stopped")
        crawl_progress("google_maps_reviews", report, remaining, stopped=True)
        raise SystemExit(143)

    previous_sigterm_handler = signal.signal(signal.SIGTERM, stop_handler)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            browser_context = browser.new_context(locale="vi-VN", timezone_id="Asia/Ho_Chi_Minh")
            crawler = GoogleMapsReviewsCrawler(browser_context)
            try:
                for row in data.to_dict("records"):
                    place = _build_place(row)
                    if not place.place_id or not place.place_name:
                        metrics.mark("skipped")
                        remaining -= 1
                        continue

                    if not plan and not refresh_success and checkpoint.is_fresh(
                        place.place_id,
                        _int_or_default(row.get("crawl_interval_days"), 30),
                    ):
                        metrics.mark("skipped")
                        remaining -= 1
                        continue

                    try:
                        reviews = crawler.crawl_place(place)
                        new_reviews = _append(reviews, existing_ids)
                        metrics.add("reviews_found", len(reviews))
                        metrics.add("new_reviews", new_reviews)
                        if reviews:
                            bronze.write([review.__dict__ for review in reviews], source_id=place.place_id)

                        crawl_status = crawler.last_status
                        if not reviews:
                            metrics.add("empty_reviews", 1)
                            checkpoint.mark(place.place_id, "EMPTY")
                            metrics.mark("empty")
                        elif crawl_status == "PARTIAL":
                            checkpoint.mark(place.place_id, "PARTIAL")
                            metrics.mark("success")
                        else:
                            checkpoint.mark(place.place_id, "SUCCESS")
                            metrics.mark("success")
                    except Exception as error:
                        checkpoint.mark(place.place_id, type(error).__name__, error_message=str(error))
                        metrics.mark("failed")
                        print(f"[ERROR] place_id={place.place_id}: {error}", flush=True)

                    remaining -= 1
                    report = metrics.write()
                    crawl_progress("google_maps_reviews", report, remaining)
                    if delay_seconds:
                        time.sleep(delay_seconds)
            finally:
                crawler.close()
                browser_context.close()
                browser.close()
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm_handler)

    report = metrics.finish()
    if env_bool("GOOGLE_MAPS_REVIEWS_REQUIRE_DATA", False) and report.get("reviews_found", 0) == 0:
        raise RuntimeError("Review smoke test found no reviews")
    if report.get("failed", 0):
        raise RuntimeError(f"Google Maps reviews had {report['failed']} failed places")


if __name__ == "__main__":
    run()
