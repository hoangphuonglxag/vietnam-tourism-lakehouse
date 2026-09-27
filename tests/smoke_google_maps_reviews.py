"""Run a real Google Maps review crawl for one reference place.

Examples:
    python tests/smoke_google_maps_reviews.py
    python tests/smoke_google_maps_reviews.py --name "thác Thăng thiên" --max-reviews 10
    python tests/smoke_google_maps_reviews.py --name "thác Thăng thiên" --headed
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PLACES_FILE = ROOT / "data" / "reference" / "places.csv"
sys.path.insert(0, str(ROOT))

from script.crawl_data.crawlers.google_maps.reviews import (  # noqa: E402
    GoogleMapsReviewsCrawler,
    Place,
)


def read_place(name: str) -> Place:
    with PLACES_FILE.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        for row in rows:
            place_name = (row.get("place_name") or "").strip()
            if place_name == name:
                return Place(
                    place_id=str(row.get("place_id") or ""),
                    place_name=place_name,
                    province_name=str(row.get("province_name") or ""),
                    latitude=str(row.get("latitude") or ""),
                    longitude=str(row.get("longitude") or ""),
                )
    raise ValueError(f"Place not found in {PLACES_FILE}: {name!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="thác Thăng thiên")
    parser.add_argument("--max-reviews", type=int, default=5)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--headed", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_reviews < 1:
        raise ValueError("--max-reviews must be at least 1")
    if args.attempts < 1:
        raise ValueError("--attempts must be at least 1")

    place = read_place(args.name)
    print(f"PLACE: {place.place_name} ({place.province_name})", flush=True)

    reviews = []
    with sync_playwright() as playwright:
        for attempt in range(1, args.attempts + 1):
            print(f"ATTEMPT: {attempt}/{args.attempts}", flush=True)
            browser = playwright.chromium.launch(headless=not args.headed)
            context = browser.new_context(
                locale="vi-VN",
                timezone_id="Asia/Ho_Chi_Minh",
                viewport={"width": 1366, "height": 900},
            )
            crawler = GoogleMapsReviewsCrawler(context)
            try:
                reviews = crawler.crawl_place(place, max_count=args.max_reviews)
            finally:
                crawler.close()
                browser.close()
            if reviews:
                break

    print(f"REVIEWS: {len(reviews)}", flush=True)
    if not reviews:
        print("SMOKE TEST FAILED: no reviews returned", file=sys.stderr)
        return 1

    first = reviews[0]
    print(f"FIRST REVIEW: {first.review_text or '<empty text>'}", flush=True)
    print("SMOKE TEST PASSED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
