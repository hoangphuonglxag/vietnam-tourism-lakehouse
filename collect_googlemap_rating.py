import csv
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
from playwright.sync_api import sync_playwright


# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = Path("data/places.csv")

OUTPUT_FILE = Path(
    "data/google_maps_ratings.csv"
)

ERROR_FILE = Path(
    "data/google_maps_errors.csv"
)

# ------------------------------------------------------------
# TEST MODE
# ------------------------------------------------------------

TEST_MODE = False

# Chỉ dùng khi TEST_MODE = True
TEST_PROVINCE = "Đà Nẵng"

# ------------------------------------------------------------
# Browser
# ------------------------------------------------------------

HEADLESS = os.getenv(
    "HEADLESS",
    "false"
).lower() == "true"

PAGE_TIMEOUT = 60_000

# Delay giữa các place
MIN_DELAY = 2
MAX_DELAY = 5


# ============================================================
# CSV SCHEMA
# ============================================================

OUTPUT_FIELDS = [
    "place_id",
    "place_name",

    "province_id",
    "province_name",

    "google_maps_url",

    "google_rating",
    "google_review_count",

    "rating_5_count",
    "rating_4_count",
    "rating_3_count",
    "rating_2_count",
    "rating_1_count",

    "crawl_status",
    "error_message",
    "crawled_at",
]


ERROR_FIELDS = [
    "place_id",
    "place_name",

    "province_id",
    "province_name",

    "error_type",
    "error_message",

    "failed_at",
]


# ============================================================
# HELPERS
# ============================================================

def now_iso():
    return datetime.now(
        timezone.utc
    ).isoformat()


def parse_rating_distribution(labels):

    result = {
        5: 0,
        4: 0,
        3: 0,
        2: 0,
        1: 0,
    }

    pattern = re.compile(
        r"([1-5])\s*sao,\s*([\d.,]+)\s*bài\s+đánh\s+giá",
        re.IGNORECASE
    )

    for label in labels:

        if not label:
            continue

        match = pattern.search(label)

        if not match:
            continue

        star = int(
            match.group(1)
        )

        count = (
            match.group(2)
            .replace(".", "")
            .replace(",", "")
        )

        try:
            result[star] = int(count)
        except ValueError:
            pass

    return result


# ============================================================
# BUILD GOOGLE MAP SEARCH URL
# ============================================================

def build_search_url(place):

    name = (
        place.get("place_name")
        or place.get("name_vi")
        or place.get("name_en")
        or ""
    ).strip()

    province = (
        place.get("province_name")
        or ""
    ).strip()

    query = (
        f"{name}, {province}, Vietnam"
    )

    return (
        "https://www.google.com/maps/search/"
        "?api=1&query="
        + quote(query)
    )


# ============================================================
# OPEN PLACE
# ============================================================

def open_place(page, place):

    # Nếu sau này places.csv có google_maps_url
    # thì ưu tiên URL đó.

    url = (
        place.get("google_maps_url")
        or ""
    ).strip()

    if not url:
        url = build_search_url(
            place
        )

    print(
        f"  Search URL: {url}"
    )

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=PAGE_TIMEOUT
    )

    page.wait_for_timeout(
        4000
    )


# ============================================================
# EXTRACT RATING
# ============================================================

def extract_rating(page):

    overall_rating = None

    # --------------------------------------------------------
    # Overall rating
    # --------------------------------------------------------

    rating_candidates = page.locator(
        '[role="img"][aria-label*="sao"]'
    )

    count = rating_candidates.count()

    for i in range(
        min(count, 30)
    ):

        label = (
            rating_candidates
            .nth(i)
            .get_attribute(
                "aria-label"
            )
        )

        if not label:
            continue

        match = re.search(
            r"([0-5](?:[.,]\d+)?)\s*sao",
            label,
            re.IGNORECASE
        )

        if not match:
            continue

        value = (
            match.group(1)
            .replace(",", ".")
        )

        try:

            value = float(value)

            if 0 <= value <= 5:

                overall_rating = value

                break

        except ValueError:
            continue

    # --------------------------------------------------------
    # Distribution
    # --------------------------------------------------------

    rows = page.locator(
        'tr[role="img"][aria-label]'
    )

    labels = []

    for i in range(
        rows.count()
    ):

        label = (
            rows.nth(i)
            .get_attribute(
                "aria-label"
            )
        )

        if label:
            labels.append(label)

    distribution = (
        parse_rating_distribution(
            labels
        )
    )

    total_reviews = sum(
        distribution.values()
    )

    return {

        "google_rating":
            overall_rating,

        "google_review_count":
            total_reviews,

        "rating_5_count":
            distribution[5],

        "rating_4_count":
            distribution[4],

        "rating_3_count":
            distribution[3],

        "rating_2_count":
            distribution[2],

        "rating_1_count":
            distribution[1],
    }


# ============================================================
# LOAD EXISTING PLACE IDS
# ============================================================

def load_existing_ids():

    existing = set()

    if not OUTPUT_FILE.exists():
        return existing

    with OUTPUT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:

            place_id = (
                row.get("place_id")
                or ""
            ).strip()

            status = (
                row.get("crawl_status")
                or ""
            ).strip()

            # Chỉ skip record đã crawl thành công.
            #
            # Nếu status = error
            # → lần chạy sau được retry.

            if (
                place_id
                and status == "success"
            ):

                existing.add(
                    place_id
                )

    return existing


def summarize_existing_by_province(existing_ids):

    if not existing_ids:
        return pd.DataFrame()

    if not OUTPUT_FILE.exists():
        return pd.DataFrame()

    rows = pd.read_csv(
        OUTPUT_FILE,
        dtype={
            "place_id": str,
            "province_id": str,
        }
    )

    if rows.empty:
        return pd.DataFrame()

    rows = rows[
        rows["place_id"].isin(existing_ids)
    ].copy()

    if rows.empty:
        return pd.DataFrame()

    summary = (
        rows.groupby(
            ["province_id", "province_name"],
            dropna=False,
        )
        .size()
        .reset_index(name="reused_count")
        .sort_values("reused_count", ascending=False)
    )

    return summary


# ============================================================
# INIT OUTPUT FILE
# ============================================================

def ensure_output_file():

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    if not OUTPUT_FILE.exists():

        with OUTPUT_FILE.open(
            "w",
            encoding="utf-8-sig",
            newline=""
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=OUTPUT_FIELDS
            )

            writer.writeheader()


def ensure_error_file():

    ERROR_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    if not ERROR_FILE.exists():

        with ERROR_FILE.open(
            "w",
            encoding="utf-8-sig",
            newline=""
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=ERROR_FIELDS
            )

            writer.writeheader()


# ============================================================
# APPEND SUCCESS
# ============================================================

def append_result(row):

    with OUTPUT_FILE.open(
        "a",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=OUTPUT_FIELDS
        )

        writer.writerow(row)

        f.flush()


# ============================================================
# APPEND ERROR
# ============================================================

def append_error(
    place,
    error_type,
    error_message
):

    row = {

        "place_id":
            place.get(
                "place_id",
                ""
            ),

        "place_name":
            place.get(
                "place_name",
                ""
            ),

        "province_id":
            place.get(
                "province_id",
                ""
            ),

        "province_name":
            place.get(
                "province_name",
                ""
            ),

        "error_type":
            error_type,

        "error_message":
            error_message,

        "failed_at":
            now_iso(),
    }

    with ERROR_FILE.open(
        "a",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=ERROR_FIELDS
        )

        writer.writerow(row)

        f.flush()


# ============================================================
# LOAD PLACES
# ============================================================

def load_places():

    with INPUT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        places = list(
            csv.DictReader(f)
        )

    # --------------------------------------------------------
    # TEST MODE
    # --------------------------------------------------------

    if TEST_MODE:

        places = [
            p
            for p in places
            if (
                p.get(
                    "province_name",
                    ""
                ).strip()
                == TEST_PROVINCE
            )
        ]

    return places


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("GOOGLE MAPS RATING COLLECTOR")
    print("=" * 70)

    ensure_output_file()
    ensure_error_file()

    places = load_places()

    print(
        f"Places selected: {len(places)}"
    )

    if TEST_MODE:

        print(
            f"TEST MODE: ON"
        )

        print(
            f"Province: {TEST_PROVINCE}"
        )

    else:

        print(
            "TEST MODE: OFF"
        )

        print(
            "Crawling ALL places"
        )

    # --------------------------------------------------------
    # Existing successful records
    # --------------------------------------------------------

    existing_ids = (
        load_existing_ids()
    )

    print(
        f"Already successful: "
        f"{len(existing_ids)}"
    )

    existing_summary = summarize_existing_by_province(
        existing_ids
    )

    if not existing_summary.empty:

        print()
        print("Reused successful records by province:")

        print(
            existing_summary.to_string(index=False)
        )

    remaining = [
        p
        for p in places
        if p.get(
            "place_id",
            ""
        ) not in existing_ids
    ]

    print(
        f"Remaining: "
        f"{len(remaining)}"
    )

    print(
        f"Reuse ratio: "
        f"{len(existing_ids)}/{len(places)}"
    )

    if not remaining:

        print()
        print(
            "Nothing to crawl."
        )

        return

    # --------------------------------------------------------
    # Counters
    # --------------------------------------------------------

    success_count = 0
    error_count = 0
    skip_count = 0

    # --------------------------------------------------------
    # Playwright
    # --------------------------------------------------------

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=HEADLESS
        )

        context = (
            browser.new_context(
                locale="vi-VN"
            )
        )

        page = context.new_page()

        page.set_default_timeout(
            PAGE_TIMEOUT
        )

        # ----------------------------------------------------
        # Crawl
        # ----------------------------------------------------

        for index, place in enumerate(
            remaining,
            start=1
        ):

            place_id = (
                place.get(
                    "place_id",
                    ""
                ).strip()
            )

            place_name = (
                place.get(
                    "place_name",
                    ""
                ).strip()
            )

            province = (
                place.get(
                    "province_name",
                    ""
                ).strip()
            )

            print()
            print(
                "-" * 70
            )

            print(
                f"[{index}/{len(remaining)}] "
                f"{place_id}"
            )

            print(
                f"  {place_name}"
            )

            print(
                f"  Province: {province}"
            )

            # ------------------------------------------------
            # Safety check
            # ------------------------------------------------

            if place_id in existing_ids:

                print(
                    "  SKIP - already successful"
                )

                skip_count += 1

                continue

            # ------------------------------------------------
            # Default result
            # ------------------------------------------------

            row = {

                "place_id":
                    place_id,

                "place_name":
                    place_name,

                "province_id":
                    place.get(
                        "province_id",
                        ""
                    ),

                "province_name":
                    province,

                "google_maps_url":
                    "",

                "google_rating":
                    "",

                "google_review_count":
                    "",

                "rating_5_count":
                    0,

                "rating_4_count":
                    0,

                "rating_3_count":
                    0,

                "rating_2_count":
                    0,

                "rating_1_count":
                    0,

                "crawl_status":
                    "",

                "error_message":
                    "",

                "crawled_at":
                    now_iso(),
            }

            # ------------------------------------------------
            # Crawl
            # ------------------------------------------------

            try:

                open_place(
                    page,
                    place
                )

                result = (
                    extract_rating(page)
                )

                row.update(
                    result
                )

                row["crawl_status"] = (
                    "success"
                )

                # ------------------------------------------------
                # SAVE IMMEDIATELY
                # ------------------------------------------------

                append_result(
                    row
                )

                existing_ids.add(
                    place_id
                )

                success_count += 1

                print(
                    f"  rating = "
                    f"{result['google_rating']}"
                )

                print(
                    f"  reviews = "
                    f"{result['google_review_count']}"
                )

                print(
                    f"  distribution = "
                    f"5★ {result['rating_5_count']} | "
                    f"4★ {result['rating_4_count']} | "
                    f"3★ {result['rating_3_count']} | "
                    f"2★ {result['rating_2_count']} | "
                    f"1★ {result['rating_1_count']}"
                )

            except Exception as e:

                error_message = str(e)

                row["crawl_status"] = (
                    "error"
                )

                row["error_message"] = (
                    error_message
                )

                # ------------------------------------------------
                # Lưu lỗi riêng
                # ------------------------------------------------

                append_error(
                    place,
                    type(e).__name__,
                    error_message
                )

                error_count += 1

                print(
                    f"  ERROR: "
                    f"{error_message}"
                )

                print(
                    "  → Saved to "
                    "google_maps_errors.csv"
                )

            # ------------------------------------------------
            # Delay
            # ------------------------------------------------

            delay = (
                MIN_DELAY
                + (
                    (MAX_DELAY - MIN_DELAY)
                    * 0.5
                )
            )

            time.sleep(delay)

        browser.close()

    # ========================================================
    # SUMMARY
    # ========================================================

    print()
    print("=" * 70)
    print("DONE")
    print("=" * 70)

    print(
        f"Selected: {len(places)}"
    )

    print(
        f"Already successful: "
        f"{len(existing_ids) - success_count}"
    )

    print(
        f"New success: "
        f"{success_count}"
    )

    print(
        f"Errors: "
        f"{error_count}"
    )

    print(
        f"Output: "
        f"{OUTPUT_FILE}"
    )

    print(
        f"Errors: "
        f"{ERROR_FILE}"
    )


if __name__ == "__main__":
    main()