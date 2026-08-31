import csv
import hashlib
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = Path("data/places.csv")
OUTPUT_FILE = Path("data/google_maps_reviews.csv")

# Google Maps renders reviews dynamically. Keep this finite so the crawler
# cannot get stuck when selectors or scrolling behavior change.
MAX_REVIEWS_PER_PLACE = int(os.getenv("MAX_REVIEWS_PER_PLACE", "100"))
MAX_SCROLL_ATTEMPTS = int(os.getenv("MAX_SCROLL_ATTEMPTS", "25"))
SCROLL_PAUSE_SECONDS = float(os.getenv("SCROLL_PAUSE_SECONDS", "1.5"))

HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
USE_SYSTEM_CHROME = os.getenv("USE_SYSTEM_CHROME", "false").lower() == "true"
CHROME_PROFILE_DIR = os.getenv("CHROME_PROFILE_DIR", "").strip()
CHROME_PROFILE_NAME = os.getenv("CHROME_PROFILE_NAME", "").strip()
SLOW_MO_MS = int(os.getenv("SLOW_MO_MS", "0"))
PAGE_TIMEOUT_MS = int(os.getenv("PAGE_TIMEOUT_MS", "45000"))
LOAD_RETRIES = int(os.getenv("LOAD_RETRIES", "2"))

# Use PLACE_IDS for a comma-separated allowlist, for example:
# PLACE_IDS=OSM_way_359114064,OSM_way_186249226
PLACE_IDS = [
    place_id.strip()
    for place_id in os.getenv("PLACE_IDS", os.getenv("TEST_PLACE_ID", "")).split(",")
    if place_id.strip()
]

# Set TEST_LIMIT=5 while developing if you want to crawl only a few places.
TEST_LIMIT = int(os.getenv("TEST_LIMIT", "0"))
TEST_PROVINCE = os.getenv("TEST_PROVINCE", "").strip()

SOURCE_NAME = "Google Maps"

OUTPUT_FIELDS = [
    "review_id",
    "place_id",
    "rating",
    "review_text",
    "review_date",
    "likes_count",
    "source",
    "crawled_at_utc",
]

REVIEW_CARD_SELECTORS = [
    # data-review-id is the most useful stable marker when Google exposes it.
    'div[data-review-id]',
    # Common Google Maps review card class. Class names can change, so it is
    # kept as a fallback rather than the only strategy.
    "div.jftiEf",
]

REVIEW_TEXT_SELECTORS = [
    ".wiI7pd",
    "span[jsan*='wiI7pd']",
]

REVIEW_DATE_SELECTORS = [
    ".rsqaWe",
    "span.rsqaWe",
]


@dataclass(frozen=True)
class Place:
    place_id: str
    place_name: str
    province_name: str
    latitude: str
    longitude: str


@dataclass
class Review:
    review_id: str
    place_id: str
    rating: int | None
    review_text: str | None
    review_date: str | None
    likes_count: int | None
    source: str
    crawled_at_utc: str


def log(level: str, message: str) -> None:
    print(f"[{level}] {message}", flush=True)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def parse_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(\d[\d.,]*)", value)
    if not match:
        return None
    digits = re.sub(r"[^\d]", "", match.group(1))
    if not digits:
        return None
    return int(digits)


def parse_rating_from_label(label: str | None) -> int | None:
    if not label:
        return None

    patterns = [
        r"([1-5])\s*sao",
        r"([1-5])\s*star",
    ]
    for pattern in patterns:
        match = re.search(pattern, label, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def ensure_output_file() -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not OUTPUT_FILE.exists():
        with OUTPUT_FILE.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()


def load_existing_review_ids() -> set[str]:
    if not OUTPUT_FILE.exists():
        return set()

    existing_ids: set[str] = set()
    with OUTPUT_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            review_id = clean_text(row.get("review_id"))
            if review_id:
                existing_ids.add(review_id)

    return existing_ids


def load_existing_review_counts() -> dict[str, int]:
    if not OUTPUT_FILE.exists():
        return {}

    df = pd.read_csv(OUTPUT_FILE, dtype=str, encoding="utf-8-sig")
    if df.empty or "place_id" not in df.columns:
        return {}

    return df.groupby("place_id", dropna=False).size().to_dict()


def append_reviews(reviews: list[Review]) -> None:
    if not reviews:
        return

    with OUTPUT_FILE.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS)
        for review in reviews:
            writer.writerow(
                {
                    "review_id": review.review_id,
                    "place_id": review.place_id,
                    "rating": review.rating,
                    "review_text": review.review_text,
                    "review_date": review.review_date,
                    "likes_count": review.likes_count,
                    "source": review.source,
                    "crawled_at_utc": review.crawled_at_utc,
                }
            )
        file.flush()


def load_places() -> list[Place]:
    df = pd.read_csv(INPUT_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    df.columns = [column.replace("\ufeff", "").strip() for column in df.columns]

    required_columns = {"place_id", "place_name", "latitude", "longitude"}
    missing = sorted(required_columns - set(df.columns))
    if missing:
        raise ValueError(f"Missing required columns in {INPUT_FILE}: {missing}")

    if TEST_PROVINCE and "province_name" in df.columns:
        df = df[df["province_name"].str.strip() == TEST_PROVINCE]

    if PLACE_IDS:
        df = df[df["place_id"].str.strip().isin(PLACE_IDS)]

    if TEST_LIMIT > 0:
        df = df.head(TEST_LIMIT)

    places: list[Place] = []
    for row in df.to_dict("records"):
        place_id = clean_text(row.get("place_id"))
        if not place_id:
            log("WARNING", "Skipping row without place_id")
            continue

        name = (
            clean_text(row.get("place_name"))
            or clean_text(row.get("name_vi"))
            or clean_text(row.get("name_en"))
            or ""
        )
        if not name:
            log("WARNING", f"Skipping place_id={place_id}: missing place name")
            continue

        places.append(
            Place(
                place_id=place_id,
                place_name=name,
                province_name=clean_text(row.get("province_name")) or "",
                latitude=clean_text(row.get("latitude")) or "",
                longitude=clean_text(row.get("longitude")) or "",
            )
        )

    return places


def build_maps_search_url(place: Place) -> str:
    location = ""
    if place.latitude and place.longitude:
        location = f" {place.latitude},{place.longitude}"

    query = f"{place.place_name}, {place.province_name}, Vietnam{location}"
    return "https://www.google.com/maps/search/?api=1&query=" + quote(query)


def accept_consent_if_present(page: Page) -> None:
    labels = [
        "Accept all",
        "I agree",
        "Agree",
        "Chấp nhận tất cả",
        "Tôi đồng ý",
    ]
    for label in labels:
        button = page.get_by_role("button", name=re.compile(label, re.IGNORECASE))
        try:
            if button.count() and button.first.is_visible(timeout=1500):
                button.first.click(timeout=3000)
                return
        except PlaywrightError:
            continue


def detect_blocking_page(page: Page) -> str | None:
    text = page.locator("body").inner_text(timeout=5000).lower()
    if "unusual traffic" in text:
        return "automation_block"

    if "captcha" in text or "not a robot" in text:
        return "captcha"

    if "sign in to continue" in text:
        return "login_required"

    if "xác minh rằng bạn không phải là robot" in text:
        return "verification"

    return None


def open_place(page: Page, place: Place) -> bool:
    url = build_maps_search_url(place)
    last_error: Exception | None = None

    for attempt in range(1, LOAD_RETRIES + 2):
        try:
            log("INFO", f"Opening Google Maps attempt={attempt}: {place.place_name}")
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            accept_consent_if_present(page)

            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                log("WARNING", "Google Maps did not reach networkidle; continuing after DOM load")

            blocking_reason = detect_blocking_page(page)
            if blocking_reason:
                log(
                    "ERROR",
                    f"Google Maps blocked or restricted this session: {blocking_reason}. Skipping gracefully.",
                )
                return False

            wait_for_place_panel(page)
            return True
        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            last_error = exc
            log("WARNING", f"Load failed attempt={attempt}: {exc}")

    log("ERROR", f"Failed to open place_id={place.place_id}: {last_error}")
    return False


def wait_for_place_panel(page: Page) -> None:
    # The panel normally contains a heading and buttons/tabs such as Reviews.
    # Avoid depending on one generated class name here.
    page.locator("h1, [role='main'], [role='feed']").first.wait_for(timeout=PAGE_TIMEOUT_MS)


def click_first_visible(locator: Locator, timeout_ms: int = 5000) -> bool:
    count = min(locator.count(), 10)
    for index in range(count):
        candidate = locator.nth(index)
        try:
            if candidate.is_visible(timeout=1000):
                candidate.click(timeout=timeout_ms)
                return True
        except PlaywrightError:
            continue
    return False


def open_reviews(page: Page) -> bool:
    review_tab_pattern = re.compile(r"(Bài đánh giá|Đánh giá|Reviews)", re.IGNORECASE)
    candidates = [
        page.get_by_role("tab", name=review_tab_pattern),
        page.get_by_role("button", name=review_tab_pattern),
        page.locator(
            'button[aria-label*="Bài đánh giá"], '
            'button[aria-label*="Đánh giá"], '
            'button[aria-label*="Reviews"]'
        ),
        page.locator(
            'a[aria-label*="Bài đánh giá"], '
            'a[aria-label*="Đánh giá"], '
            'a[aria-label*="Reviews"]'
        ),
    ]

    for candidate in candidates:
        try:
            if click_first_visible(candidate):
                page.wait_for_timeout(1000)
                return True
        except PlaywrightError:
            continue

    # Some result pages open directly with the review feed already present.
    if get_review_cards(page).count() > 0:
        return True

    return False


def sort_reviews_newest(page: Page) -> None:
    sort_buttons = [
        page.get_by_role("button", name=re.compile(r"(Sắp xếp|Sort)", re.IGNORECASE)),
        page.locator('button[aria-label*="Sắp xếp"], button[aria-label*="Sort"]'),
    ]

    clicked = False
    for button in sort_buttons:
        try:
            if click_first_visible(button, timeout_ms=3000):
                clicked = True
                break
        except PlaywrightError:
            continue

    if not clicked:
        return

    newest_options = [
        page.get_by_role("menuitemradio", name=re.compile(r"(Mới nhất|Newest|Most recent)", re.IGNORECASE)),
        page.get_by_role("menuitem", name=re.compile(r"(Mới nhất|Newest|Most recent)", re.IGNORECASE)),
        page.get_by_text(re.compile(r"^(Mới nhất|Newest|Most recent)$", re.IGNORECASE)),
    ]

    for option in newest_options:
        try:
            if click_first_visible(option, timeout_ms=3000):
                page.wait_for_timeout(1000)
                return
        except PlaywrightError:
            continue


def get_review_cards(page: Page) -> Locator:
    for selector in REVIEW_CARD_SELECTORS:
        locator = page.locator(selector)
        try:
            if locator.count() > 0:
                return locator
        except PlaywrightError:
            continue
    return page.locator("div[data-review-id]")


# def find_review_scroll_container(page: Page) -> Locator:
#     # Google Maps review cards live in a scrollable feed/dialog. Prefer ARIA
#     # roles because they survive class-name changes more often.
#     candidates = [
#         page.locator("[role='feed']"),
#         page.locator("[role='main'] div").filter(has=get_review_cards(page).first),
#         page.locator("div.m6QErb.DxyBCb.kA9KIf.dS8AEf"),
#     ]

#     for candidate in candidates:
#         try:
#             if candidate.count() and candidate.first.is_visible(timeout=1000):
#                 return candidate.first
#         except PlaywrightError:
#             continue

#     return page.locator("body")
# def find_review_scroll_container(page: Page) -> Locator:
#     """
#     Tìm vùng scroll chứa review của Google Maps.
#     Ưu tiên [role=feed], sau đó tìm ancestor có review card.
#     """

#     # --------------------------------------------------------
#     # 1. Google Maps thường dùng role="feed"
#     # --------------------------------------------------------

#     feeds = page.locator("[role='feed']")

#     try:
#         for i in range(feeds.count()):
#             feed = feeds.nth(i)

#             if feed.is_visible(timeout=500):

#                 try:
#                     review_count = feed.locator(
#                         'div[data-review-id]'
#                     ).count()

#                     if review_count > 0:
#                         return feed

#                 except PlaywrightError:
#                     pass

#                 try:
#                     review_count = feed.locator(
#                         "div.jftiEf"
#                     ).count()

#                     if review_count > 0:
#                         return feed

#                 except PlaywrightError:
#                     pass

#     except PlaywrightError:
#         pass

#     # --------------------------------------------------------
#     # 2. Tìm element cha của review card
#     # --------------------------------------------------------

#     cards = get_review_cards(page)

#     try:

#         if cards.count() > 0:

#             first_card = cards.first

#             # Đi lên các ancestor để tìm element scrollable
#             container = first_card.locator(
#                 "xpath=ancestor::*[self::div]"
#             )

#             count = min(
#                 container.count(),
#                 10
#             )

#             for i in range(count):

#                 candidate = container.nth(i)

#                 try:

#                     if not candidate.is_visible(
#                         timeout=300
#                     ):
#                         continue

#                     is_scrollable = candidate.evaluate(
#                         """
#                         (element) => {
#                             return (
#                                 element.scrollHeight >
#                                 element.clientHeight
#                             );
#                         }
#                         """
#                     )

#                     if is_scrollable:
#                         return candidate

#                 except PlaywrightError:
#                     continue

#     except PlaywrightError:
#         pass

#     # --------------------------------------------------------
#     # 3. Fallback selector phổ biến của Google Maps
#     # --------------------------------------------------------

#     fallback = page.locator(
#         "div.m6QErb.DxyBCb.kA9KIf.dS8AEf"
#     )

#     try:
#         if fallback.count() > 0:
#             return fallback.first
#     except PlaywrightError:
#         pass

#     # --------------------------------------------------------
#     # 4. Cuối cùng dùng body
#     # --------------------------------------------------------

#     log(
#         "WARNING",
#         "Could not identify review scroll container; using body fallback"
#     )

#     return page.locator("body")
def find_review_scroll_container(page: Page) -> Locator | None:
    """
    Tìm đúng container chứa danh sách review của Google Maps.

    Google Maps thay đổi class thường xuyên nên ưu tiên:
    1. [role="feed"]
    2. container có review card bên trong
    3. các selector class cũ làm fallback
    """

    # --------------------------------------------------------
    # 1. Ưu tiên role=feed
    # --------------------------------------------------------

    feeds = page.locator("[role='feed']")

    try:
        for i in range(feeds.count()):
            feed = feeds.nth(i)

            if feed.is_visible(timeout=500):
                cards = feed.locator(
                    "div[data-review-id], div.jftiEf"
                )

                if cards.count() > 0:
                    log(
                        "INFO",
                        f"Found review feed via [role='feed'], "
                        f"cards={cards.count()}"
                    )
                    return feed

    except PlaywrightError:
        pass

    # --------------------------------------------------------
    # 2. Tìm ancestor của review card
    # --------------------------------------------------------

    cards = get_review_cards(page)

    try:
        if cards.count() > 0:

            first_card = cards.first

            # Đi lên nhiều cấp để tìm element có scroll
            for level in range(1, 8):

                try:

                    parent = first_card.locator(
                        "/.." * level
                    ).first

                    if not parent.is_visible(timeout=500):
                        continue

                    scroll_info = parent.evaluate(
                        """
                        element => ({
                            scrollHeight: element.scrollHeight,
                            clientHeight: element.clientHeight,
                            overflowY: getComputedStyle(element).overflowY
                        })
                        """
                    )

                    if (
                        scroll_info["scrollHeight"]
                        > scroll_info["clientHeight"] + 100
                    ):
                        log(
                            "INFO",
                            "Found scrollable review container "
                            f"at ancestor level={level}"
                        )

                        return parent

                except PlaywrightError:
                    continue

    except PlaywrightError:
        pass

    # --------------------------------------------------------
    # 3. Fallback selector cũ
    # --------------------------------------------------------

    fallback_selectors = [
        "div.m6QErb.DxyBCb.kA9KIf.dS8AEf",
        "div.m6QErb",
    ]

    for selector in fallback_selectors:

        try:

            candidates = page.locator(selector)

            for i in range(candidates.count()):

                candidate = candidates.nth(i)

                if not candidate.is_visible(timeout=500):
                    continue

                info = candidate.evaluate(
                    """
                    element => ({
                        scrollHeight: element.scrollHeight,
                        clientHeight: element.clientHeight
                    })
                    """
                )

                if (
                    info["scrollHeight"]
                    > info["clientHeight"] + 100
                ):
                    log(
                        "INFO",
                        f"Found scroll container via fallback: {selector}"
                    )

                    return candidate

        except PlaywrightError:
            continue

    log(
        "WARNING",
        "Could not identify review scroll container"
    )

    return None


def expand_visible_review_text(page: Page) -> None:
    more_buttons = [
        page.get_by_role("button", name=re.compile(r"(Thêm|More)", re.IGNORECASE)),
        page.locator('button[aria-label*="Thêm"], button[aria-label*="More"]'),
    ]
    for buttons in more_buttons:
        count = min(buttons.count(), 30)
        for index in range(count):
            try:
                button = buttons.nth(index)
                if button.is_visible(timeout=300):
                    button.click(timeout=1000)
            except PlaywrightError:
                continue


def scroll_reviews(page: Page) -> None:
    """
    Scroll review list cho tới khi:
    - đạt MAX_REVIEWS_PER_PLACE
    - hết review
    - hoặc selector/DOM không còn load review mới
    """

    log(
        "INFO",
        f"Start scrolling reviews: "
        f"target={MAX_REVIEWS_PER_PLACE}, "
        f"max_attempts={MAX_SCROLL_ATTEMPTS}"
    )

    container = find_review_scroll_container(page)

    if container is None:
        log(
            "ERROR",
            "Review scroll container not found"
        )
        return

    stagnant_attempts = 0
    last_unique_count = 0

    for attempt in range(
        1,
        MAX_SCROLL_ATTEMPTS + 1
    ):

        cards = get_review_cards(page)

        dom_count = cards.count()

        # ----------------------------------------------------
        # Đếm review ID thực tế
        # ----------------------------------------------------

        unique_ids = set()

        for i in range(
            min(dom_count, MAX_REVIEWS_PER_PLACE)
        ):

            try:

                review_id = cards.nth(i).get_attribute(
                    "data-review-id",
                    timeout=500
                )

                if review_id:
                    unique_ids.add(review_id)

            except PlaywrightError:
                continue

        unique_count = len(unique_ids)

        log(
            "INFO",
            f"Scroll {attempt}/{MAX_SCROLL_ATTEMPTS}: "
            f"DOM_cards={dom_count}, "
            f"unique_reviews={unique_count}/"
            f"{MAX_REVIEWS_PER_PLACE}"
        )

        # ----------------------------------------------------
        # Đã đủ 100
        # ----------------------------------------------------

        if unique_count >= MAX_REVIEWS_PER_PLACE:

            log(
                "SUCCESS",
                f"Reached target: "
                f"{unique_count} reviews"
            )

            return

        # ----------------------------------------------------
        # Kiểm tra có review mới không
        # ----------------------------------------------------

        if unique_count <= last_unique_count:

            stagnant_attempts += 1

            log(
                "INFO",
                f"No new review IDs. "
                f"stagnant={stagnant_attempts}/5"
            )

        else:

            stagnant_attempts = 0

        last_unique_count = unique_count

        # ----------------------------------------------------
        # Không có review mới quá lâu
        # ----------------------------------------------------

        if stagnant_attempts >= 5:

            log(
                "WARNING",
                "No new review IDs after 5 attempts. "
                "Stopping."
            )

            break

        # ----------------------------------------------------
        # Scroll container
        # ----------------------------------------------------

        try:

            container.evaluate(
                """
                element => {
                    element.scrollTop = element.scrollHeight;
                }
                """
            )

        except PlaywrightError as exc:

            log(
                "WARNING",
                f"Container scroll failed: {exc}"
            )

            # ------------------------------------------------
            # Fallback: mouse wheel
            # ------------------------------------------------

            try:

                page.mouse.wheel(
                    0,
                    4000
                )

            except PlaywrightError as wheel_error:

                log(
                    "ERROR",
                    f"Mouse wheel fallback failed: "
                    f"{wheel_error}"
                )

        # ----------------------------------------------------
        # Chờ Google Maps render thêm review
        # ----------------------------------------------------

        try:

            page.wait_for_function(
                """
                ([oldCount]) => {
                    const selectors = [
                        'div[data-review-id]',
                        'div.jftiEf'
                    ];

                    const count = selectors.reduce(
                        (total, selector) =>
                            total +
                            document.querySelectorAll(selector).length,
                        0
                    );

                    return count > oldCount;
                }
                """,
                arg=[dom_count],
                timeout=5000,
            )

            log(
                "INFO",
                "New review cards detected"
            )

        except PlaywrightTimeoutError:

            # Không coi timeout này là crawler error.
            # Google Maps có thể đang load chậm.
            log(
                "WARNING",
                "No new review cards detected "
                "within 5 seconds"
            )

        # ----------------------------------------------------
        # Cho browser thời gian render
        # ----------------------------------------------------

        time.sleep(
            SCROLL_PAUSE_SECONDS
        )

    log(
        "INFO",
        f"Scrolling finished. "
        f"Final unique reviews={last_unique_count}"
    )

def locator_text_or_none(parent: Locator, selectors: list[str]) -> str | None:
    for selector in selectors:
        try:
            locator = parent.locator(selector)
            if locator.count() > 0:
                text = clean_text(locator.first.inner_text(timeout=1000))
                if text:
                    return text
        except PlaywrightError:
            continue
    return None


def get_rating(card: Locator) -> int | None:
    candidates = [
        card.locator('[role="img"][aria-label*="sao"]'),
        card.locator('[role="img"][aria-label*="star"]'),
        card.locator('[aria-label*="sao"]'),
        card.locator('[aria-label*="star"]'),
    ]
    for locator in candidates:
        count = min(locator.count(), 5)
        for index in range(count):
            try:
                label = locator.nth(index).get_attribute("aria-label", timeout=1000)
                rating = parse_rating_from_label(label)
                if rating is not None:
                    return rating
            except PlaywrightError:
                continue
    return None


def get_review_text(card: Locator) -> str | None:
    text = locator_text_or_none(card, REVIEW_TEXT_SELECTORS)
    if text:
        return text

    # Empty-text reviews are valid on Google Maps. Returning NULL is better
    # than inventing content from nearby labels.
    return None


def get_review_date(card: Locator) -> str | None:
    return locator_text_or_none(card, REVIEW_DATE_SELECTORS)


def get_likes_count(card: Locator) -> int | None:
    candidates = [
        card.locator('button[aria-label*="hữu ích"]'),
        card.locator('button[aria-label*="helpful"]'),
        card.locator('button[aria-label*="like"]'),
    ]

    for locator in candidates:
        count = min(locator.count(), 5)
        for index in range(count):
            try:
                label = locator.nth(index).get_attribute("aria-label", timeout=1000)
                likes = parse_int(label)
                if likes is not None:
                    return likes
            except PlaywrightError:
                continue
    return None


def deterministic_review_id(
    place_id: str,
    google_review_id: str | None,
    rating: int | None,
    review_text: str | None,
    review_date: str | None,
    card_text: str | None,
) -> str:
    if google_review_id:
        return f"google_maps_{google_review_id}"

    raw = "|".join(
        [
            place_id,
            str(rating or ""),
            review_text or "",
            review_date or "",
            card_text or "",
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"google_maps_{place_id}_{digest}"


def extract_reviews(page: Page, place: Place) -> list[Review]:
    expand_visible_review_text(page)

    cards = get_review_cards(page)

    card_count = min(
        cards.count(),
        MAX_REVIEWS_PER_PLACE
    )

    log(
        "INFO",
        (
            f"Extracting {card_count} reviews "
            f"for place_id={place.place_id}"
        ),
    )

    crawled_at = utc_now_iso()

    reviews: list[Review] = []

    seen_in_place: set[str] = set()

    for index in range(card_count):

        card = cards.nth(index)

        try:

            google_review_id = clean_text(
                card.get_attribute(
                    "data-review-id",
                    timeout=1000
                )
            )

            rating = get_rating(card)

            review_text = get_review_text(card)

            review_date = get_review_date(card)

            likes_count = get_likes_count(card)

            card_text = clean_text(
                card.inner_text(
                    timeout=1000
                )
            )

            review_id = deterministic_review_id(
                place_id=place.place_id,
                google_review_id=google_review_id,
                rating=rating,
                review_text=review_text,
                review_date=review_date,
                card_text=card_text,
            )

            if review_id in seen_in_place:
                continue

            seen_in_place.add(review_id)

            reviews.append(
                Review(
                    review_id=review_id,
                    place_id=place.place_id,
                    rating=rating,
                    review_text=review_text,
                    review_date=review_date,
                    likes_count=likes_count,
                    source=SOURCE_NAME,
                    crawled_at_utc=crawled_at,
                )
            )

        except PlaywrightError as exc:

            log(
                "WARNING",
                (
                    f"Could not parse review "
                    f"index={index}, "
                    f"place_id={place.place_id}: "
                    f"{exc}"
                ),
            )

    log(
        "INFO",
        (
            f"Extracted {len(reviews)} reviews "
            f"for place_id={place.place_id}"
        ),
    )

    return reviews



class GoogleMapsReviewsCrawler:
    def __init__(self, context: BrowserContext) -> None:
        self.context = context
        self.page: Page = self.context.new_page()
        self.page.set_default_timeout(PAGE_TIMEOUT_MS)

    def close(self) -> None:
        self.context.close()

    def crawl_place(self, place: Place) -> list[Review]:
        log("INFO", f"Crawling: {place.place_name}")

        if not open_place(self.page, place):
            return []

        if not open_reviews(self.page):
            log("WARNING", f"No reviews tab found place_id={place.place_id}")
            return []

        sort_reviews_newest(self.page)

        if get_review_cards(self.page).count() == 0:
            log("WARNING", f"No reviews found place_id={place.place_id}")
            return []

        scroll_reviews(self.page)
        reviews = extract_reviews(self.page, place)

        if not reviews:
            log("WARNING", f"No parseable reviews found place_id={place.place_id}")

        return reviews


def filter_new_reviews(reviews: list[Review], existing_ids: set[str]) -> list[Review]:
    new_reviews = []
    for review in reviews:
        if review.review_id in existing_ids:
            continue
        new_reviews.append(review)
        existing_ids.add(review.review_id)
    return new_reviews


def main() -> None:
    log("INFO", "GOOGLE MAPS REVIEWS CRAWLER")
    ensure_output_file()

    places = load_places()
    existing_ids = load_existing_review_ids()
    existing_counts = load_existing_review_counts()

    log("INFO", f"Places loaded: {len(places)}")
    log("INFO", f"Existing reviews: {len(existing_ids)}")
    log("INFO", f"MAX_REVIEWS_PER_PLACE={MAX_REVIEWS_PER_PLACE}")

    remaining = [
        place
        for place in places
        if existing_counts.get(place.place_id, 0) < MAX_REVIEWS_PER_PLACE
    ]
    log("INFO", f"Places remaining: {len(remaining)}")

    with sync_playwright() as playwright:
        browser: Browser | None = None

        context_options = {
            "locale": "vi-VN",
            "timezone_id": "Asia/Ho_Chi_Minh",
            "viewport": {"width": 1366, "height": 900},
        }

        launch_options = {
            "headless": HEADLESS,
            "slow_mo": SLOW_MO_MS,
        }
        if USE_SYSTEM_CHROME:
            launch_options["channel"] = "chrome"

        if CHROME_PROFILE_NAME:
            launch_options["args"] = [f"--profile-directory={CHROME_PROFILE_NAME}"]

        if CHROME_PROFILE_DIR:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=CHROME_PROFILE_DIR,
                **launch_options,
                **context_options,
            )
        else:
            browser = playwright.chromium.launch(**launch_options)
            context = browser.new_context(**context_options)

        crawler = GoogleMapsReviewsCrawler(context)

        try:
            for index, place in enumerate(remaining, start=1):
                log("INFO", f"[{index}/{len(remaining)}] place_id={place.place_id}")

                try:
                    reviews = crawler.crawl_place(place)
                    new_reviews = filter_new_reviews(reviews, existing_ids)
                    append_reviews(new_reviews)

                    existing_counts[place.place_id] = existing_counts.get(place.place_id, 0) + len(
                        new_reviews
                    )

                    log(
                        "SUCCESS",
                        (
                            f"place_id={place.place_id}, "
                            f"reviews_seen={len(reviews)}, "
                            f"new_reviews={len(new_reviews)}"
                        ),
                    )
                except Exception as exc:
                    log("ERROR", f"Failed to crawl place_id={place.place_id}: {type(exc).__name__}: {exc}")
        finally:
            crawler.close()
            if browser is not None:
                browser.close()

    log("SUCCESS", f"Done. Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()