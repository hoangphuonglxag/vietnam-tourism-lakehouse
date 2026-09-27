"""
Crawl review Google Maps:

place name + province
-> tab Bài đánh giá
-> Mới nhất
-> cuộn bằng wheel thật
-> parse review
-> ghi CSV + bronze JSONL

Chạy 1 place:
    python tests/crawl_review.py \
        --name "Công viên Nước Đầm Sen" \
        --province "Hồ Chí Minh" \
        --max-reviews 30

Chạy nhiều place:
    python tests/crawl_review.py --limit 3 --max-reviews 100
    python tests/crawl_review.py --limit 3 --force --max-reviews 100
    python tests/crawl_review.py --limit 3 --headless

Lưu ý:
    Không dùng JS để set scrollTop.
    Google Maps cần wheel event thật để lazy-load review.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import random
import re
import sys
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright


# ============================================================================
# WINDOWS UTF-8
# ============================================================================

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ============================================================================
# PATH
# ============================================================================

ROOT = Path(__file__).resolve().parents[1]

PLACES_FILE = ROOT / "data" / "reference" / "places.csv"
REVIEWS_FILE = ROOT / "tests" / "gg_maps_reviews.csv"
BRONZE_REVIEWS_DIR = ROOT / "data" / "bronze" / "google_maps" / "reviews"
REVIEW_STATUS_FILE = ROOT / "tests" / "google_maps_review_crawl_status.csv"


# ============================================================================
# CONFIG
# ============================================================================

GOOGLE_MAPS_REVIEWS_LIMIT = int(
    os.getenv("GOOGLE_MAPS_REVIEWS_LIMIT", "0")
)

MAX_REVIEWS_PER_PLACE = int(
    os.getenv("MAX_REVIEWS_PER_PLACE", "100")
)

GOOGLE_MAPS_DELAY_SECONDS = float(
    os.getenv("GOOGLE_MAPS_DELAY_SECONDS", "1.0")
)

GOOGLE_MAPS_REVIEWS_DELAY_SECONDS = float(
    os.getenv("GOOGLE_MAPS_REVIEWS_DELAY_SECONDS", "1.0")
)

MAX_STAGNANT_WHEELS = 10


# ============================================================================
# CSV SCHEMA
# ============================================================================

FIELDS = [
    "review_id",
    "place_id",
    "rating",
    "review_text",
    "review_date",
    "likes_count",
    "source",
    "crawled_at_utc",
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


# ============================================================================
# SELECTORS / REGEX
# ============================================================================

CARD = "[data-review-id]"

TAB_RE = re.compile(
    r"Bài đánh giá|Đánh giá|Reviews?",
    re.I,
)

SORT_BTN_RE = re.compile(
    r"Sắp xếp|Sort|Phù hợp nhất|Most relevant|Mới nhất|Newest|"
    r"Cao nhất|Highest|Thấp nhất|Lowest",
    re.I,
)

NO_RESULT_RE = re.compile(
    r"không thể tìm thấy|không tìm thấy|can't find|couldn't find",
    re.I,
)

TOTAL_REVIEWS_RE = re.compile(
    r"([\d.,]+)\s*(?:bài đánh giá|đánh giá|reviews?)",
    re.I,
)


# ============================================================================
# JAVASCRIPT
# ============================================================================

COUNT_JS = """
() => new Set(
    [...document.querySelectorAll('[data-review-id]')]
        .map(e => e.getAttribute('data-review-id'))
).size
"""

TAB_SELECTED_JS = r"""
() => [...document.querySelectorAll('button[role="tab"]')].some(t =>
    t.getAttribute('aria-selected') === 'true' &&
    /Bài đánh giá|Đánh giá|Reviews?/i.test(
        (t.getAttribute('aria-label') || '') + ' ' + t.innerText
    )
)
"""

EXPAND_JS = """
() => {
    const buttons = document.querySelectorAll(
        '[data-review-id] button.w8nwRe, ' +
        '[data-review-id] button[aria-label="Xem thêm"], ' +
        '[data-review-id] button[aria-label="See more"]'
    );

    for (const button of buttons) {
        try {
            button.click();
        } catch (_) {}
    }

    return buttons.length;
}
"""

FIND_PANEL_RECT_JS = r"""
() => {
    const card = document.querySelector('[data-review-id]');

    if (!card) {
        return {
            ok: false,
            why: 'no-review-card'
        };
    }

    let el = card.parentElement;

    while (el) {
        const style = getComputedStyle(el);

        if (
            el.scrollHeight > el.clientHeight + 20 &&
            /(auto|scroll)/.test(style.overflowY)
        ) {
            const rect = el.getBoundingClientRect();

            return {
                ok: true,
                rect: {
                    x: rect.x,
                    y: rect.y,
                    width: rect.width,
                    height: rect.height
                },
                scrollTop: el.scrollTop,
                scrollHeight: el.scrollHeight,
                clientHeight: el.clientHeight,
                overflowY: style.overflowY,
                tag: el.tagName,
                role: el.getAttribute('role')
            };
        }

        el = el.parentElement;
    }

    return {
        ok: false,
        why: 'no-scrollable-review-ancestor'
    };
}
"""

PARSE_JS = r"""
() => {
    const seen = new Map();

    document.querySelectorAll('[data-review-id]').forEach(card => {
        const id = card.getAttribute('data-review-id');

        if (id && !seen.has(id)) {
            seen.set(id, card);
        }
    });

    return [...seen.entries()].map(([id, card]) => {
        const query = selector => card.querySelector(selector);

        const star = (
            query('span.kvMYJc') ||
            query('[role="img"][aria-label]')
        )?.getAttribute('aria-label') || '';

        const textEl = [
            ...card.querySelectorAll('span.wiI7pd')
        ].find(el => !el.closest('.CDe7pd'));

        return {
            review_id: id,
            rating: (star.match(/\d+/) || [null])[0],
            review_text: (textEl?.innerText || '').trim(),
            review_date: (
                query('span.rsqaWe')?.innerText || ''
            ).trim(),
            likes_count: (
                query('span.pkWtMe')?.innerText || '0'
            ).trim(),
        };
    });
}
"""


# ============================================================================
# EXCEPTIONS
# ============================================================================

class BlockedError(Exception):
    """Google Maps bị chặn / CAPTCHA."""


class PlaceNotFound(Exception):
    """Không tìm thấy place."""


class NoReviewsTab(Exception):
    """Không mở được tab review."""


# ============================================================================
# UTILS
# ============================================================================

def log(message: str) -> None:
    print(message, flush=True)


def norm(text: str) -> str:
    text = unicodedata.normalize(
        "NFD",
        text.lower().replace("đ", "d"),
    )

    text = "".join(
        ch
        for ch in text
        if unicodedata.category(ch) != "Mn"
    )

    return " ".join(
        re.sub(r"[^a-z0-9 ]+", " ", text).split()
    )


def name_matches(wanted: str, found: str) -> bool:
    a = norm(wanted)
    b = norm(found)

    if not a or not b:
        return True

    if a in b or b in a:
        return True

    return difflib.SequenceMatcher(
        None,
        a,
        b,
    ).ratio() >= 0.6


def is_newest(text: str) -> bool:
    value = norm(text)
    return "moi nhat" in value or "newest" in value


def _pick(row: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)

        if value and value.strip():
            return value.strip()

    return ""


# ============================================================================
# GOOGLE MAPS CHECKS
# ============================================================================

def check_blocked(page) -> None:
    if (
        "/sorry/" in page.url
        or page.locator('iframe[src*="recaptcha"]').count() > 0
    ):
        raise BlockedError(
            f"Bị chặn / CAPTCHA: {page.url}"
        )


def handle_consent(page) -> None:
    if "consent.google" not in page.url:
        return

    try:
        page.get_by_role(
            "button",
            name=re.compile(
                r"Chấp nhận tất cả|Accept all|"
                r"Từ chối tất cả|Reject all",
                re.I,
            ),
        ).first.click(timeout=5000)
    except Exception:
        pass

    try:
        page.wait_for_url(
            re.compile(r"google\.[a-z.]+/maps"),
            timeout=15000,
        )
    except PWTimeout:
        pass


# ============================================================================
# PLACE LIST
# ============================================================================

def select_places(limit: int = 0) -> list[dict]:
    if not PLACES_FILE.exists():
        raise RuntimeError(
            f"Không tìm thấy places.csv: {PLACES_FILE}"
        )

    places = []

    with PLACES_FILE.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        for row in csv.DictReader(file):
            name = _pick(
                row,
                "place_name",
                "name",
                "place",
                "title",
            )

            if not name:
                continue

            places.append({
                "place_id": _pick(
                    row,
                    "place_id",
                    "id",
                ),
                "name": name,
                "province": _pick(
                    row,
                    "province_name",
                    "province",
                    "city",
                ),
            })

    return places[:limit] if limit else places


def load_place_status(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    try:
        with path.open(
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file)

            if "place_id" not in (reader.fieldnames or []):
                return {}

            return {
                row["place_id"]: row.get("status", "")
                for row in reader
                if row.get("place_id")
            }

    except Exception:
        return {}


# ============================================================================
# OPEN PLACE
# ============================================================================

def open_place(page, place: dict) -> str:
    query = (
        f'{place["name"]} {place["province"]}'
    ).strip()

    search_url = (
        "https://www.google.com/maps/search/"
        f"{quote(query)}?hl=vi"
    )

    log(f"  → search: {query}")

    page.goto(
        search_url,
        wait_until="domcontentloaded",
        timeout=30000,
    )

    handle_consent(page)
    check_blocked(page)

    page.wait_for_timeout(2500)

    if "/maps/place/" not in page.url:
        try:
            page.wait_for_function(
                "() => location.href.includes('/maps/place/') "
                "|| document.querySelectorAll('a.hfpxzc').length > 0 "
                "|| /không thể tìm thấy|không tìm thấy|can.t find/i"
                ".test(document.body.innerText)",
                timeout=15000,
            )
        except PWTimeout:
            pass

        if page.get_by_text(NO_RESULT_RE).count() > 0:
            raise PlaceNotFound(
                f'Search không ra kết quả: "{query}"'
            )

        if "/maps/place/" not in page.url:
            raise RuntimeError(
                f"Không mở được trang place. url={page.url}"
            )

    log(f"  ✓ đã vào place: {page.url}")

    check_blocked(page)

    # Cho Maps render UI ổn định rồi reload một lần.
    page.wait_for_timeout(3000)

    log("  → reload trang place")

    page.reload(
        wait_until="domcontentloaded",
        timeout=30000,
    )

    handle_consent(page)
    check_blocked(page)

    page.wait_for_timeout(5000)

    try:
        page.locator("h1.DUwDvf").first.wait_for(
            state="visible",
            timeout=15000,
        )
    except PWTimeout:
        log("  ! chưa thấy h1.DUwDvf, tiếp tục")

    found_name = ""

    try:
        found_name = page.locator(
            "h1.DUwDvf"
        ).first.inner_text(
            timeout=5000
        ).strip()
    except Exception:
        pass

    if not found_name:
        found_name = page.title().replace(
            " - Google Maps",
            "",
        ).strip()

    if found_name:
        log(f'  ✓ place hiện tại: "{found_name}"')

    return found_name


# ============================================================================
# REVIEWS TAB
# ============================================================================

def open_reviews_tab(page) -> bool:
    for attempt in range(1, 4):
        log(
            f"  → tìm tab Bài đánh giá "
            f"(lần {attempt}/3)"
        )

        tab = page.get_by_role(
            "tab",
            name=TAB_RE,
        ).first

        try:
            tab.wait_for(
                state="visible",
                timeout=5000,
            )
        except PWTimeout:
            page.wait_for_timeout(
                1000 * attempt
            )
            continue

        tab.scroll_into_view_if_needed()
        page.wait_for_timeout(200)

        try:
            tab.click(timeout=5000)
        except PWTimeout:
            continue

        try:
            page.wait_for_function(
                TAB_SELECTED_JS,
                timeout=5000,
            )
        except PWTimeout:
            pass

        try:
            page.wait_for_selector(
                CARD,
                timeout=8000,
            )

            log("  ✓ review đã render")
            return True

        except PWTimeout:
            log("  ! review chưa render")

    log("  !!! không mở được tab Bài đánh giá")

    return False


# ============================================================================
# SORT NEWEST
# ============================================================================

def sort_by_newest(page) -> bool:
    log("  → tìm nút sắp xếp")

    btn = page.locator(
        "button.HQzyZ"
    ).first

    try:
        btn.wait_for(
            state="visible",
            timeout=10000,
        )
    except PWTimeout:
        btn = page.get_by_role(
            "button",
            name=SORT_BTN_RE,
        ).first

        try:
            btn.wait_for(
                state="visible",
                timeout=8000,
            )
        except PWTimeout:
            log("  !!! không thấy nút sắp xếp")
            return False

    current = (
        btn.get_attribute("aria-label")
        or btn.inner_text()
        or ""
    ).strip()

    log(f"  nút sắp xếp hiện tại: {current!r}")

    if is_newest(current):
        log("  ✓ đã ở chế độ Mới nhất")
        return True

    log("  → click nút sắp xếp")

    try:
        btn.click(timeout=5000)
    except Exception as exc:
        log(
            f"  !!! không click được nút sắp xếp: "
            f"{exc}"
        )
        return False

    page.wait_for_timeout(700)

    newest = None

    # Cách 1: role
    try:
        candidates = page.locator(
            '[role="menuitem"], '
            '[role="menuitemradio"], '
            '[role="option"], '
            '[role="button"]'
        )

        for i in range(candidates.count()):
            element = candidates.nth(i)

            try:
                text = element.inner_text(
                    timeout=500
                ).strip()
            except Exception:
                continue

            if norm(text) == "moi nhat":
                newest = element
                break

    except Exception:
        pass

    # Cách 2: text fallback
    if newest is None:
        try:
            candidates = page.get_by_text(
                re.compile(
                    r"Mới|Newest|Mới",
                    re.I,
                )
            )

            for i in range(candidates.count()):
                element = candidates.nth(i)

                try:
                    text = element.inner_text(
                        timeout=500
                    ).strip()
                except Exception:
                    continue

                if norm(text) == "moi nhat":
                    newest = element
                    break

        except Exception:
            pass

    if newest is None:
        log("  !!! KHÔNG TÌM THẤY 'Mới nhất'")
        return False

    log("  ✓ tìm thấy option 'Mới nhất'")

    try:
        newest.click(timeout=5000)
    except Exception:
        try:
            newest.click(
                timeout=5000,
                force=True,
            )
        except Exception as exc:
            log(
                f"  !!! không click được 'Mới nhất': "
                f"{exc}"
            )
            return False

    page.wait_for_timeout(1500)

    try:
        after = (
            btn.get_attribute("aria-label")
            or btn.inner_text()
            or ""
        ).strip()
    except Exception:
        after = ""

    log(
        f"  nút sắp xếp sau khi chọn: "
        f"{after!r}"
    )

    if is_newest(after):
        log(
            "  ✓✓ Google Maps đã xác nhận: "
            "Mới nhất"
        )
        return True

    # Fallback: kiểm tra selected element
    try:
        selected = page.locator(
            '[aria-selected="true"], '
            '[aria-checked="true"], '
            '[role="menuitemradio"]'
        )

        for i in range(selected.count()):
            element = selected.nth(i)

            try:
                text = element.inner_text(
                    timeout=500
                ).strip()
            except Exception:
                continue

            if norm(text) == "moi nhat":
                log(
                    "  ✓✓ xác nhận Mới nhất "
                    "qua selected element"
                )
                return True

    except Exception:
        pass

    log(
        "  !!! chưa xác nhận được Google Maps "
        "đang ở Mới nhất"
    )

    return False


# ============================================================================
# TOTAL REVIEW COUNT
# ============================================================================

def get_total_review_count(page) -> int | None:
    selectors = [
        "div.F7nice",
        "span.F7nice",
        'button[jsaction*="reviewChart"]',
    ]

    text = ""

    for selector in selectors:
        try:
            text = page.locator(
                selector
            ).first.inner_text(
                timeout=2000
            )

            if text:
                break

        except Exception:
            continue

    if not text:
        try:
            text = page.locator(
                "h1.DUwDvf"
            ).first.locator(
                "xpath=../.."
            ).inner_text(
                timeout=2000
            )
        except Exception:
            return None

    match = TOTAL_REVIEWS_RE.search(text)

    if not match:
        return None

    try:
        return int(
            match.group(1)
            .replace(".", "")
            .replace(",", "")
        )
    except ValueError:
        return None


# ============================================================================
# REVIEW PANEL
# ============================================================================

def get_panel(page) -> dict | None:
    try:
        info = page.evaluate(
            FIND_PANEL_RECT_JS
        )
    except Exception:
        return None

    if not info or not info.get("ok"):
        return None

    return info


def get_review_count(page) -> int:
    try:
        return page.evaluate(COUNT_JS)
    except Exception:
        return 0


def get_panel_point(
    page,
) -> tuple[float, float] | None:
    panel = get_panel(page)

    if not panel:
        return None

    rect = panel["rect"]

    x = rect["x"] + rect["width"] / 2
    y = rect["y"] + max(
        rect["height"] * 0.4,
        100,
    )

    return x, y


# ============================================================================
# SCROLL + COLLECT
# ============================================================================

def scroll_and_collect(
    page,
    max_reviews: int,
) -> list[dict]:

    count = get_review_count(page)

    log(f"  review ban đầu: {count}")

    if max_reviews and count >= max_reviews:
        page.evaluate(EXPAND_JS)
        page.wait_for_timeout(500)

        return page.evaluate(PARSE_JS)[:max_reviews]

    stagnant = 0
    wheel_no = 0

    while not (
        max_reviews
        and count >= max_reviews
    ):
        wheel_no += 1

        before_count = count
        before_panel = get_panel(page)
        point = get_panel_point(page)

        if point:
            x, y = point

            page.mouse.move(x, y)

            # QUAN TRỌNG:
            # Đây là wheel event thật.
            # Không set scrollTop bằng JS.
            page.mouse.wheel(0, 500)

        else:
            log(
                "  ! không tìm được panel "
                "-> fallback keyboard End"
            )
            page.keyboard.press("End")

        delay = (
            GOOGLE_MAPS_REVIEWS_DELAY_SECONDS
            * random.uniform(0.8, 1.5)
        )

        page.wait_for_timeout(
            int(1000 * delay)
        )

        after_panel = get_panel(page)
        count = get_review_count(page)

        log(
            f"  wheel #{wheel_no}: "
            f"reviews {before_count} -> {count}"
        )

        if before_panel and after_panel:
            before_top = before_panel["scrollTop"]
            after_top = after_panel["scrollTop"]

            if after_top != before_top:
                log(
                    f"    scrollTop: "
                    f"{before_top} -> {after_top}"
                )
            else:
                log("    ! scrollTop không đổi")

        if count > before_count:
            stagnant = 0
            log("    ✓ có review mới")
        else:
            stagnant += 1

            log(
                f"    ! chưa có review mới "
                f"({stagnant}/{MAX_STAGNANT_WHEELS})"
            )

            if stagnant >= MAX_STAGNANT_WHEELS:
                log(
                    "  dừng: quá nhiều wheel liên tiếp "
                    "không có review mới"
                )
                break

    page.evaluate(EXPAND_JS)
    page.wait_for_timeout(500)

    rows = page.evaluate(PARSE_JS)

    log(
        f"  đã tải {len(rows)} review"
        + (
            f" (yêu cầu {max_reviews})"
            if max_reviews
            else ""
        )
    )

    if max_reviews:
        return rows[:max_reviews]

    return rows


# ============================================================================
# CRAWL ONE PLACE
# ============================================================================

def crawl_review(
    page,
    place: dict,
    max_reviews: int,
) -> dict:

    found_name = open_place(
        page,
        place,
    )

    matched = name_matches(
        place["name"],
        found_name,
    )

    if not matched:
        log(
            f'  !!! tên không khớp: '
            f'cần "{place["name"]}" '
            f'nhưng ra "{found_name}"'
        )

    if not open_reviews_tab(page):
        raise NoReviewsTab(
            "Không mở được tab Bài đánh giá"
        )

    if not sort_by_newest(page):
        raise RuntimeError(
            "Không thể xác nhận Google Maps "
            "đang ở chế độ 'Mới nhất'."
        )

    total = get_total_review_count(page)

    log(
        f"  tổng review Google hiển thị: "
        f"{total}"
    )

    rows = scroll_and_collect(
        page,
        max_reviews,
    )

    if not rows:
        raise RuntimeError(
            "Đã mở tab Bài đánh giá "
            "nhưng không lấy được review nào."
        )

    if (
        max_reviews
        and len(rows) >= max_reviews
    ):
        status = "success"

    elif (
        total is not None
        and len(rows) >= total
    ):
        status = "success"

    else:
        status = "partial"

    return {
        "found_name": found_name,
        "name_matched": matched,
        "url": page.url,
        "rows": rows,
        "total_reviews": total,
        "status": status,
    }


# ============================================================================
# CSV
# ============================================================================

def validate_csv_schema(path: Path) -> None:
    if (
        not path.exists()
        or path.stat().st_size == 0
    ):
        return

    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        fieldnames = (
            csv.DictReader(file).fieldnames
            or []
        )

    if fieldnames != FIELDS:
        raise RuntimeError(
            f"Schema CSV không đúng.\n"
            f"File: {path}\n"
            f"Header hiện tại: {fieldnames}\n"
            f"Header mong đợi: {FIELDS}\n"
            f"Hãy backup/xóa CSV cũ trước khi chạy lại."
        )


def append_reviews_to_csv(
    place_id: str,
    rows: list[dict],
    out_path: Path,
    crawled_at: str,
) -> int:

    out_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    validate_csv_schema(out_path)

    existing = set()

    file_exists = out_path.exists()
    file_empty = (
        not file_exists
        or out_path.stat().st_size == 0
    )

    if file_exists and not file_empty:
        with out_path.open(
            encoding="utf-8-sig",
            newline="",
        ) as file:
            for row in csv.DictReader(file):
                review_id = (
                    row.get("review_id")
                    or ""
                ).strip()

                if review_id:
                    existing.add(review_id)

    added = 0

    with out_path.open(
        "a",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS,
        )

        if file_empty:
            writer.writeheader()

        for review in rows:
            review_id = (
                review.get("review_id")
                or ""
            ).strip()

            if (
                not review_id
                or review_id in existing
            ):
                continue

            writer.writerow({
                "review_id": review_id,
                "place_id": place_id,
                "rating": review.get("rating") or "",
                "review_text": (
                    review.get("review_text")
                    or ""
                ),
                "review_date": (
                    review.get("review_date")
                    or ""
                ),
                "likes_count": (
                    re.sub(
                        r"\D",
                        "",
                        review.get("likes_count")
                        or "",
                    )
                    or "0"
                ),
                "source": "google_maps",
                "crawled_at_utc": crawled_at,
            })

            existing.add(review_id)
            added += 1

    return added


# ============================================================================
# BRONZE JSONL
# ============================================================================

def append_bronze_review(
    path: Path,
    review: dict,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "a",
        encoding="utf-8",
    ) as file:
        file.write(
            json.dumps(
                review,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )


# ============================================================================
# STATUS CSV
# ============================================================================

def upsert_review_status(
    path: Path,
    *,
    place_id: str,
    place_name: str,
    province_name: str,
    status: str,
    requested_reviews: int,
    loaded_reviews: int,
    google_review_count: int | None,
    error_message: str,
    crawled_at: str,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    rows = []

    if (
        path.exists()
        and path.stat().st_size > 0
    ):
        with path.open(
            encoding="utf-8-sig",
            newline="",
        ) as file:
            for row in csv.DictReader(file):
                if row.get("place_id") != place_id:
                    rows.append(row)

    rows.append({
        "place_id": place_id,
        "place_name": place_name,
        "province_name": province_name,
        "status": status,
        "requested_reviews": requested_reviews,
        "loaded_reviews": loaded_reviews,
        "google_review_count": (
            google_review_count
            if google_review_count is not None
            else ""
        ),
        "error_message": error_message,
        "crawled_at": crawled_at,
    })

    tmp_path = path.with_suffix(".tmp")

    with tmp_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=REVIEW_STATUS_FIELDS,
        )

        writer.writeheader()
        writer.writerows(rows)

    tmp_path.replace(path)


# ============================================================================
# MAIN
# ============================================================================
# ============================================================================
# main
# ============================================================================
def main() -> None:
    ap = argparse.ArgumentParser(description="Crawl Google Maps reviews")

    ap.add_argument(
        "--limit",
        type=int,
        default=GOOGLE_MAPS_REVIEWS_LIMIT,
        help="số place (0 = tất cả)",
    )
    ap.add_argument(
        "--max-reviews",
        type=int,
        default=MAX_REVIEWS_PER_PLACE,
        help="review/place (0 = hết)",
    )
    ap.add_argument(
        "--headless",
        action="store_true",
        help="chạy ẩn",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="crawl lại place đã success",
    )
    ap.add_argument(
        "--name",
        help="test nhanh 1 place, không cần places.csv",
    )
    ap.add_argument(
        "--province",
        default="",
        help="province đi kèm --name",
    )

    args = ap.parse_args()

    if args.max_reviews < 0:
        raise SystemExit("--max-reviews phải >= 0")

    # ------------------------------------------------------------------------
    # Run metadata
    # ------------------------------------------------------------------------
    run_started_at = datetime.now(timezone.utc)
    run_id = (
        f"google_maps-"
        f"{run_started_at.strftime('%Y%m%dT%H%M%SZ')}-"
        f"{uuid.uuid4().hex[:12]}"
    )

    crawl_date = run_started_at.strftime("%Y-%m-%d")

    bronze_dir = BRONZE_REVIEWS_DIR / f"crawl_date={crawl_date}"
    bronze_file = bronze_dir / f"part-{run_id}.jsonl"

    log(f"[RUN] {run_id}")
    log(f"[BRONZE] {bronze_file}")

    # ------------------------------------------------------------------------
    # Chọn places
    # ------------------------------------------------------------------------
    if args.name:
        places = [{
            "place_id": "TEST",
            "name": args.name,
            "province": args.province,
        }]

        todo = places

        log(
            "  [TEST MODE] không dùng URL cache, "
            "không bỏ qua place đã crawl trước đó"
        )

    else:
        places = select_places(args.limit)

        status_map = (
            {}
            if args.force
            else load_place_status(REVIEW_STATUS_FILE)
        )

        todo = [
            place
            for place in places
            if args.force
            or status_map.get(place["place_id"]) != "success"
        ]

    log(
        f"{len(places)} place, "
        f"bỏ qua {len(places) - len(todo)} place đã crawl đủ (success), "
        f"chạy {len(todo)} place"
    )

    summary = {
        "success": 0,
        "partial": 0,
        "error": 0,
        "blocked": 0,
    }

    # ------------------------------------------------------------------------
    # Browser
    # ------------------------------------------------------------------------
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=args.headless
        )

        context = browser.new_context(
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            viewport={
                "width": 1366,
                "height": 900,
            },
        )

        try:
            for index, place in enumerate(todo, 1):
                started = time.time()

                log(
                    f'[{index}/{len(todo)}] '
                    f'{place["name"]} - {place["province"]}'
                )

                page = context.new_page()
                status = "error"

                try:
                    # --------------------------------------------------------
                    # Crawl
                    # --------------------------------------------------------
                    info = crawl_review(
                        page,
                        place,
                        args.max_reviews,
                    )

                    crawled_at = datetime.now(
                        timezone.utc
                    ).isoformat(timespec="seconds")

                    status = info["status"]

                    # --------------------------------------------------------
                    # Lưu status
                    # --------------------------------------------------------
                    upsert_review_status(
                        REVIEW_STATUS_FILE,
                        place_id=place["place_id"],
                        place_name=place["name"],
                        province_name=place["province"],
                        status=status,
                        requested_reviews=args.max_reviews,
                        loaded_reviews=len(info["rows"]),
                        google_review_count=info["total_reviews"],
                        error_message="",
                        crawled_at=crawled_at,
                    )

                    # --------------------------------------------------------
                    # Lưu bronze JSONL
                    # --------------------------------------------------------
                    for review in info["rows"]:
                        append_bronze_review(
                            bronze_file,
                            {
                                "run_id": run_id,
                                "crawl_date": crawl_date,
                                "place_id": place["place_id"],
                                "place_name": place["name"],
                                "province": place["province"],
                                "source": "google_maps",
                                "crawled_at_utc": crawled_at,
                                "status": status,
                                "total_reviews": info["total_reviews"],
                                **review,
                            },
                        )

                    # --------------------------------------------------------
                    # Lưu CSV tổng
                    # --------------------------------------------------------
                    added = sumary_review(
                        place["place_id"],
                        info["rows"],
                        REVIEWS_FILE,
                        crawled_at,
                    )

                    log(
                        f"  -> {len(info['rows'])} review "
                        f"(tổng Google: {info['total_reviews']}), "
                        f"ghi mới {added}, "
                        f"status={status}"
                    )

                except BlockedError as e:
                    status = "blocked"
                    log(f"  !!! {e} -> dừng toàn bộ crawl")

                except PlaceNotFound as e:
                    status = "error"
                    log(f"  !!! {e}")

                except NoReviewsTab as e:
                    status = "error"
                    log(f"  !!! {e}")

                except Exception as e:
                    status = "error"
                    log(
                        f"  !!! lỗi: "
                        f"{type(e).__name__}: {e}"
                    )

                finally:
                    page.close()

                # ------------------------------------------------------------
                # Summary
                # ------------------------------------------------------------
                summary[status] += 1

                elapsed = round(time.time() - started, 1)
                log(f"  ({elapsed}s)")

                # Google bị block -> dừng ngay
                if status == "blocked":
                    break

                # Delay giữa các place
                time.sleep(
                    GOOGLE_MAPS_DELAY_SECONDS
                    * random.uniform(0.8, 1.6)
                )

        finally:
            browser.close()

    # ------------------------------------------------------------------------
    # Kết quả cuối
    # ------------------------------------------------------------------------
    log(
        "Xong. "
        f"success={summary['success']} "
        f"partial={summary['partial']} "
        f"error={summary['error']} "
        f"blocked={summary['blocked']} "
        f"-> {REVIEWS_FILE}"
    )

    log(f"Bronze: {bronze_file}")


if __name__ == "__main__":
    main()
