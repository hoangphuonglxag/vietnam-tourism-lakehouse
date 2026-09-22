"""
Crawl review Google Maps theo:
place name + province
-> tab Bài đánh giá
-> Mới nhất
-> cuộn
-> parse review
-> ghi CSV

Chạy thử 1 place:
    python tests/crawl_review.py --name "Công viên Nước Đầm Sen" --province "Hồ Chí Minh" --max-reviews 30

Test lại cùng 1 place nhiều lần:
    python tests/crawl_review.py --name "Công viên Nước Đầm Sen" --province "Hồ Chí Minh" --max-reviews 100

Chạy nhiều place:
    python tests/crawl_review.py --limit 3 --max-reviews 100

Chạy nhiều place, kể cả place đã có trong CSV:
    python tests/crawl_review.py --limit 3 --force --max-reviews 100

Chạy headless:
    python tests/crawl_review.py --limit 3 --headless

LƯU Ý:
    Trong giai đoạn TEST, URL CACHE ĐÃ ĐƯỢC TẮT.
    Mỗi lần chạy sẽ mở/search place lại từ đầu.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import os
import json
import uuid
import random
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright


# ============================================================================
# Windows UTF-8
# ============================================================================

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ============================================================================
# PATH
# ============================================================================

ROOT = Path(__file__).resolve().parents[1]

PLACES_FILE = (
    ROOT
    / "data"
    / "reference"
    / "places.csv"
)

REVIEWS_FILE = (
    ROOT
    / "tests"
    / "gg_maps_reviews.csv"
)

BRONZE_REVIEWS_DIR = (
    ROOT
    / "data"
    / "bronze"
    / "google_maps"
    / "reviews"
)

DEBUG_DIR = (
    ROOT
    / "tests"
    / "debug"
)


# ============================================================================
# CONFIG
# ============================================================================

GOOGLE_MAPS_REVIEWS_LIMIT = int(
    os.getenv(
        "GOOGLE_MAPS_REVIEWS_LIMIT",
        "0"
    )
)

MAX_REVIEWS_PER_PLACE = int(
    os.getenv(
        "MAX_REVIEWS_PER_PLACE",
        "100"
    )
)

GOOGLE_MAPS_DELAY_SECONDS = float(
    os.getenv(
        "GOOGLE_MAPS_DELAY_SECONDS",
        "1.0"
    )
)

GOOGLE_MAPS_REVIEWS_DELAY_SECONDS = float(
    os.getenv(
        "GOOGLE_MAPS_REVIEWS_DELAY_SECONDS",
        "1.0"
    )
)


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


# ============================================================================
# SELECTORS / REGEX
# ============================================================================

CARD = "[data-review-id]"

TAB_RE = re.compile(
    r"Bài đánh giá|Đánh giá|Reviews?",
    re.I
)

SORT_BTN_RE = re.compile(
    r"Sắp xếp|Sort|Phù hợp nhất|Most relevant|Mới nhất|Newest|Cao nhất|Highest|Thấp nhất|Lowest",
    re.I
)

NEWEST_RE = re.compile(
    r"Mới nhất|Newest",
    re.I
)


# ============================================================================
# JS
# ============================================================================

COUNT_JS = """
() => new Set(
    [...document.querySelectorAll('[data-review-id]')]
        .map(e => e.getAttribute('data-review-id'))
).size
"""


FIRST_ID_JS = """
() => document.querySelector('[data-review-id]')
    ?.getAttribute('data-review-id') || ''
"""


EXPAND_JS = """
() => {
    document.querySelectorAll(
        '[data-review-id] button.w8nwRe,' +
        '[data-review-id] button[aria-label="Xem thêm"],' +
        '[data-review-id] button[aria-label="See more"]'
    ).forEach(b => {
        try {
            b.click();
        } catch (e) {}
    });
}
"""


PARSE_JS = r"""
() => {

    const seen = new Map();

    document.querySelectorAll(
        '[data-review-id]'
    ).forEach(e => {

        const id =
            e.getAttribute('data-review-id');

        if (
            id &&
            !seen.has(id)
        ) {
            seen.set(id, e);
        }
    });

    return [...seen.entries()].map(
        ([id, c]) => {

            const q = s =>
                c.querySelector(s);

            const star =
                (
                    q('span.kvMYJc') ||
                    q('[role="img"][aria-label]')
                )
                ?.getAttribute(
                    'aria-label'
                ) || '';

            const textEl =
                [
                    ...c.querySelectorAll(
                        'span.wiI7pd'
                    )
                ]
                .find(
                    e => !e.closest('.CDe7pd')
                );

            return {

                review_id: id,

                rating:
                    (
                        star.match(/\d+/) ||
                        [null]
                    )[0],

                review_text:
                    (
                        textEl?.innerText ||
                        ''
                    ).trim(),

                review_date:
                    (
                        q('span.rsqaWe')
                        ?.innerText ||
                        ''
                    ).trim(),

                likes_count:
                    (
                        q('span.pkWtMe')
                        ?.innerText ||
                        '0'
                    ).trim(),
            };
        }
    );
}
"""


# ============================================================================
# EXCEPTIONS
# ============================================================================

class BlockedError(Exception):
    """
    Google chặn / CAPTCHA.
    """
    pass


# ============================================================================
# LOG
# ============================================================================

def log(msg: str) -> None:
    print(
        msg,
        flush=True
    )


# ============================================================================
# NORMALIZE TEXT
# ============================================================================

def norm(s: str) -> str:

    s = (
        s
        .lower()
        .replace("đ", "d")
    )

    s = unicodedata.normalize(
        "NFD",
        s
    )

    s = "".join(
        ch
        for ch in s
        if unicodedata.category(ch) != "Mn"
    )

    return " ".join(
        re.sub(
            r"[^a-z0-9 ]+",
            " ",
            s
        ).split()
    )


def name_matches(
    wanted: str,
    found: str
) -> bool:

    a = norm(wanted)
    b = norm(found)

    if not a or not b:
        return True

    if a in b:
        return True

    if b in a:
        return True

    ratio = difflib.SequenceMatcher(
        None,
        a,
        b
    ).ratio()

    return ratio >= 0.6


# ============================================================================
# GOOGLE BLOCK CHECK
# ============================================================================

def check_blocked(page) -> None:

    if (
        "/sorry/" in page.url
        or page.locator(
            'iframe[src*="recaptcha"]'
        ).count() > 0
    ):
        raise BlockedError(
            f"Bị chặn / CAPTCHA: {page.url}"
        )


# ============================================================================
# CONSENT
# ============================================================================

def handle_consent(page) -> None:

    if "consent.google" not in page.url:
        return

    try:

        button = page.get_by_role(
            "button",
            name=re.compile(
                r"Chấp nhận tất cả|Accept all|Từ chối tất cả|Reject all",
                re.I
            )
        ).first

        button.click(
            timeout=5000
        )

    except Exception:
        pass

    try:

        page.wait_for_url(
            re.compile(
                r"google\.[a-z.]+/maps"
            ),
            timeout=15000
        )

    except PWTimeout:
        pass


# ============================================================================
# READ PLACES
# ============================================================================

def _pick(
    row: dict,
    *keys: str
) -> str:

    for k in keys:

        v = row.get(k)

        if v and v.strip():
            return v.strip()

    return ""


def select_places(
    limit: int = 0
) -> list[dict]:

    places = []

    if not PLACES_FILE.exists():

        raise RuntimeError(
            f"Không tìm thấy places.csv: "
            f"{PLACES_FILE}"
        )

    with PLACES_FILE.open(
        encoding="utf-8-sig",
        newline=""
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:

            name = _pick(
                row,
                "place_name",
                "name",
                "place",
                "title"
            )

            if not name:
                continue

            places.append(
                {
                    "place_id": _pick(
                        row,
                        "place_id",
                        "id"
                    ),
                    "name": name,
                    "province": _pick(
                        row,
                        "province_name",
                        "province",
                        "city"
                    ),
                }
            )

    if limit:
        return places[:limit]

    return places


# ============================================================================
# LOAD DONE PLACE IDS
# ============================================================================

def load_done_place_ids(
    path: Path
) -> set[str]:

    if not path.exists():
        return set()

    try:

        with path.open(
            encoding="utf-8-sig",
            newline=""
        ) as f:

            reader = csv.DictReader(f)

            fieldnames = (
                reader.fieldnames
                or []
            )

            if "place_id" not in fieldnames:

                log(
                    "  ! CSV cũ không có "
                    "'place_id'"
                )

                log(
                    f"  ! Header hiện tại: "
                    f"{fieldnames}"
                )

                log(
                    "  ! coi như chưa có "
                    "place nào được crawl"
                )

                return set()

            result = set()

            for row in reader:

                pid = (
                    row.get("place_id")
                    or ""
                ).strip()

                if pid:
                    result.add(pid)

            return result

    except Exception as e:

        log(
            f"  ! không đọc được CSV: "
            f"{type(e).__name__}: {e}"
        )

        return set()


# ============================================================================
# OPEN PLACE
#
# IMPORTANT:
# Không dùng URL CACHE trong bản TEST này.
# ============================================================================
def open_place(
    page,
    place: dict
) -> str:

    query = (
        f'{place["name"]} '
        f'{place["province"]}'
    ).strip()

    search_url = (
        "https://www.google.com/maps/search/"
        f"{quote(query)}?hl=vi"
    )

    log(
        f"  → search Google Maps: "
        f"{query}"
    )

    page.goto(
        search_url,
        wait_until="domcontentloaded",
        timeout=30000
    )

    handle_consent(page)
    check_blocked(page)

    # Google Maps tiếp tục redirect/render sau domcontentloaded
    page.wait_for_timeout(3000)

    # =========================================================================
    # Kiểm tra lại URL sau khi Google render
    # =========================================================================

    if "/maps/place/" not in page.url:

        log(
            f"  → vẫn đang ở search page: {page.url}"
        )

        # ---------------------------------------------------------------------
        # Chờ result hoặc redirect sang place.
        #
        # Không chỉ chờ a.hfpxzc vì Google đôi khi redirect thẳng
        # search -> place.
        # ---------------------------------------------------------------------

        try:

            page.wait_for_function(
                """
                () => {
                    return (
                        location.href.includes('/maps/place/')
                        ||
                        document.querySelector('a.hfpxzc') !== null
                    );
                }
                """,
                timeout=15000
            )

        except PWTimeout:

            # Có thể URL đã đổi sang place ngay lúc timeout
            if "/maps/place/" not in page.url:

                dump_debug(
                    page,
                    "search_no_result"
                )

                raise RuntimeError(
                    "Không tìm thấy kết quả place. "
                    f"url={page.url}"
                )

        # ---------------------------------------------------------------------
        # Nếu Google đã redirect sang place trong lúc chờ
        # thì KHÔNG cần tìm a.hfpxzc nữa.
        # ---------------------------------------------------------------------

        if "/maps/place/" not in page.url:

            results = page.locator(
                "a.hfpxzc"
            )

            try:
                results.first.wait_for(
                    state="visible",
                    timeout=5000
                )
            except PWTimeout:

                # Kiểm tra URL lần cuối
                if "/maps/place/" in page.url:
                    pass
                else:
                    dump_debug(
                        page,
                        "search_no_result"
                    )

                    raise RuntimeError(
                        "Có search page nhưng không tìm thấy "
                        "result place. "
                        f"url={page.url}"
                    )

            # -----------------------------------------------------------------
            # Nếu vẫn là search page thì lấy result
            # -----------------------------------------------------------------

            if "/maps/place/" not in page.url:

                count = results.count()

                if count == 0:

                    dump_debug(
                        page,
                        "search_no_result"
                    )

                    raise RuntimeError(
                        "Không có result place. "
                        f"url={page.url}"
                    )

                log(
                    f"  ✓ tìm thấy {count} kết quả"
                )

                clicked = False

                # -------------------------------------------------------------
                # Tìm result khớp tên
                # -------------------------------------------------------------

                for i in range(
                    min(count, 10)
                ):

                    result = results.nth(i)

                    try:

                        text = (
                            result
                            .inner_text(
                                timeout=1000
                            )
                            .strip()
                        )

                    except Exception:

                        text = ""

                    if name_matches(
                        place["name"],
                        text
                    ):

                        log(
                            f'  ✓ result khớp: "{text}"'
                        )

                        result.click()

                        clicked = True

                        break

                # -------------------------------------------------------------
                # Không match -> lấy result đầu
                # -------------------------------------------------------------

                if not clicked:

                    log(
                        "  ! không tìm thấy "
                        "result khớp tên"
                    )

                    log(
                        "  → click result đầu tiên"
                    )

                    results.first.click()

                # -------------------------------------------------------------
                # Chờ Google chuyển sang place
                # -------------------------------------------------------------

                try:

                    page.wait_for_url(
                        re.compile(
                            r"/maps/place/"
                        ),
                        timeout=15000
                    )

                except PWTimeout:
                    pass

                page.wait_for_timeout(3000)

    # =========================================================================
    # Sau toàn bộ search -> result -> click
    # BẮT BUỘC kiểm tra URL cuối cùng
    # =========================================================================

    if "/maps/place/" not in page.url:

        dump_debug(
            page,
            "place_navigation_failed"
        )

        raise RuntimeError(
            "Không mở được trang place. "
            f"url={page.url}"
        )

    log(
        f"  ✓ đã vào place: {page.url}"
    )

    check_blocked(page)

    # =========================================================================
    # Chờ H1
    # =========================================================================

    try:

        page.locator(
            "h1.DUwDvf"
        ).first.wait_for(
            state="visible",
            timeout=15000
        )

    except PWTimeout:

        log(
            "  ! chưa thấy h1.DUwDvf, "
            "tiếp tục kiểm tra UI"
        )

    # =========================================================================
    # Lấy tên place
    # =========================================================================

    found_name = ""

    try:

        found_name = (
            page.locator(
                "h1.DUwDvf"
            )
            .first
            .inner_text(
                timeout=5000
            )
            .strip()
        )

    except Exception:
        pass

    # =========================================================================
    # Fallback title
    # =========================================================================

    if not found_name:

        try:

            found_name = (
                page.title()
                .replace(
                    " - Google Maps",
                    ""
                )
                .strip()
            )

        except Exception:

            found_name = ""

    if found_name:

        log(
            f'  ✓ place hiện tại: "{found_name}"'
        )

    return found_name

def open_reviews_tab(page) -> bool:
    """
    Mở tab Bài đánh giá.

    Google Maps đôi khi render thiếu tab sau lần load đầu.
    Nếu retry DOM không thành công thì reload trang và thử lại.
    """

    MAX_RELOADS = 0

    for reload_no in range(MAX_RELOADS + 1):

        if reload_no == 0:
            log("  → tìm tab Bài đánh giá")
        else:
            log(
                f"  → reload trang và thử lại "
                f"({reload_no}/{MAX_RELOADS})"
            )

            current_url = page.url

            page.reload(
                wait_until="domcontentloaded",
                timeout=30000
            )

            handle_consent(page)
            check_blocked(page)

            # Cho Maps hydrate lại
            page.wait_for_timeout(3000)

            log(
                f"  ✓ reload xong: {page.url}"
            )

            # Đảm bảo vẫn ở đúng place
            if "/maps/place/" not in page.url:
                log(
                    "  ! reload xong không còn ở place"
                )
                continue

        # =========================================================
        # Thử tìm tab nhiều lần mà KHÔNG reload
        # =========================================================

        for attempt in range(1, 4):

            log(
                f"  → tìm tab Bài đánh giá "
                f"(lần {attempt}/3)"
            )

            try:

                tab = page.get_by_role(
                    "tab",
                    name=TAB_RE
                ).first

                tab.wait_for(
                    state="visible",
                    timeout=5000
                )

                log(
                    "  ✓ đã thấy tab Bài đánh giá"
                )

                tab.scroll_into_view_if_needed()

                page.wait_for_timeout(300)

                tab.click(
                    timeout=5000
                )

                # Chờ review thực sự xuất hiện
                try:

                    page.wait_for_selector(
                        CARD,
                        timeout=10000
                    )

                    log(
                        "  ✓ review đã render"
                    )

                    return True

                except PWTimeout:

                    log(
                        "  ! đã click tab nhưng "
                        "review chưa render"
                    )

            except PWTimeout:

                log(
                    "  ! chưa thấy tab"
                )

            # Cho Maps thêm thời gian render
            page.wait_for_timeout(
                1500 * attempt
            )

        # =========================================================
        # Hết retry DOM → vòng ngoài sẽ reload
        # =========================================================

        if reload_no < MAX_RELOADS:
            log(
                "  ! chưa thấy tab sau nhiều lần thử"
            )
            log(
                "  → chuẩn bị reload Google Maps"
            )

    # =============================================================
    # Thất bại hoàn toàn
    # =============================================================

    tabs = []

    try:
        tabs = page.locator(
            'button[role="tab"]'
        ).all_inner_texts()
    except Exception:
        pass

    log(
        "  !!! không mở được tab Bài đánh giá "
        f"sau {MAX_RELOADS} lần reload"
    )

    log(
        f"  tabs hiện tại: {tabs}"
    )

    dump_debug(
        page,
        "reviews_tab_not_found"
    )

    return False
    """
    Mở tab Bài đánh giá.
    Google Maps render UI không ổn định nên retry nhiều lần.
    """

    for attempt in range(1, 6):

        log(
            f"  → tìm tab Bài đánh giá "
            f"(lần {attempt}/5)"
        )

        # ---------------------------------------------------------
        # Cách 1: role=tab
        # ---------------------------------------------------------

        tab = page.get_by_role(
            "tab",
            name=TAB_RE
        ).first

        try:
            tab.wait_for(
                state="visible",
                timeout=4000
            )

            log("  ✓ đã thấy tab Bài đánh giá")

            tab.scroll_into_view_if_needed()

            page.wait_for_timeout(300)

            tab.click(
                timeout=5000
            )

            # Chờ review card
            try:
                page.wait_for_selector(
                    CARD,
                    timeout=10000
                )

                log("  ✓ review đã render")
                return True

            except PWTimeout:
                log(
                    "  ! đã click tab nhưng "
                    "review chưa render"
                )

        except PWTimeout:
            pass

        # ---------------------------------------------------------
        # Cách 2: tìm text trực tiếp
        # ---------------------------------------------------------

        try:

            candidates = page.get_by_text(
                re.compile(
                    r"^Bài đánh giá$|^Đánh giá$|^Reviews?$",
                    re.I
                )
            )

            count = candidates.count()

            if count:

                for i in range(count):

                    el = candidates.nth(i)

                    try:

                        if not el.is_visible():
                            continue

                        log(
                            "  ✓ tìm thấy text "
                            f"Bài đánh giá ({i})"
                        )

                        el.scroll_into_view_if_needed()

                        el.click(
                            timeout=5000
                        )

                        page.wait_for_timeout(1500)

                        if page.locator(
                            CARD
                        ).count():

                            log(
                                "  ✓ review đã render"
                            )

                            return True

                    except Exception:
                        continue

        except Exception:
            pass

        # ---------------------------------------------------------
        # Cách 3: đợi Google Maps hydrate thêm
        # ---------------------------------------------------------

        page.wait_for_timeout(
            1500 * attempt
        )

        # ---------------------------------------------------------
        # Cách 4: scroll nhẹ panel chính
        # để ép Maps render lazy UI
        # ---------------------------------------------------------

        try:

            page.mouse.wheel(
                0,
                300
            )

        except Exception:
            pass

    # -------------------------------------------------------------
    # Không tìm được
    # -------------------------------------------------------------

    tabs = []

    try:
        tabs = page.locator(
            'button[role="tab"]'
        ).all_inner_texts()

    except Exception:
        pass

    log(
        f"  ! không mở được tab Bài đánh giá "
        f"sau 5 lần thử. tabs={tabs}"
    )

    dump_debug(
        page,
        "reviews_tab_not_found"
    )

    return False

# ============================================================================
# SORT -> NEWEST
# ============================================================================

def sort_by_newest(
    page
) -> bool:

    # =========================================================================
    # Tìm nút sort
    # =========================================================================

    btn = page.locator(
        "button.HQzyZ"
    ).first

    try:

        btn.wait_for(
            state="visible",
            timeout=15000
        )

    except PWTimeout:

        btn = page.get_by_role(
            "button",
            name=SORT_BTN_RE
        ).first

        try:

            btn.wait_for(
                state="visible",
                timeout=10000
            )

        except PWTimeout:

            log(
                "  ! không thấy nút sắp xếp"
            )

            return False

    current = (
        btn.get_attribute(
            "aria-label"
        )
        or btn.inner_text()
        or ""
    ).strip()

    log(
        f"  nút sắp xếp ban đầu: "
        f"{current!r}"
    )

    # =========================================================================
    # Đã là Mới nhất
    # =========================================================================

    if (
        "moi nhat" in norm(current)
        or "newest" in norm(current)
    ):

        log(
            "  ✓ đã ở chế độ Mới nhất"
        )

        return True

    # =========================================================================
    # Click sort
    # =========================================================================

    first_before = page.evaluate(
        FIRST_ID_JS
    )

    log(
        "  → click nút sắp xếp"
    )

    try:

        btn.click(
            timeout=5000
        )

    except Exception as e:

        log(
            f"  ! không click được "
            f"nút sắp xếp: {e}"
        )

        return False

    page.wait_for_timeout(
        500
    )

    # =========================================================================
    # Chờ menu
    # =========================================================================

    menu = page.locator(
        '[role="menu"]'
    ).last

    try:

        menu.wait_for(
            state="visible",
            timeout=5000
        )

        log(
            "  ✓ menu sắp xếp đã mở"
        )

    except PWTimeout:

        log(
            "  ! không thấy [role=menu], "
            "fallback toàn page"
        )

    # =========================================================================
    # Tìm Mới nhất
    # =========================================================================

    newest_re = re.compile(
        r"^Mới nhất$|^Mới nhất$|^Newest$",
        re.I
    )

    newest = None

    # -------------------------------------------------------------------------
    # Cách 1: trong menu
    # -------------------------------------------------------------------------

    try:

        newest = menu.get_by_text(
            newest_re
        ).first

        newest.wait_for(
            state="visible",
            timeout=3000
        )

        log(
            f"  → tìm thấy option: "
            f"{newest.inner_text()!r}"
        )

    except Exception:

        newest = None

    # -------------------------------------------------------------------------
    # Cách 2: toàn page
    # -------------------------------------------------------------------------

    if newest is None:

        try:

            newest = page.get_by_text(
                newest_re
            ).last

            newest.wait_for(
                state="visible",
                timeout=3000
            )

            log(
                f"  → tìm thấy option: "
                f"{newest.inner_text()!r}"
            )

        except Exception:

            newest = None

    # -------------------------------------------------------------------------
    # Cách 3: quét text normalized
    # -------------------------------------------------------------------------

    if newest is None:

        candidates = page.locator(
            "div, span, button"
        )

        for i in range(
            candidates.count()
        ):

            el = candidates.nth(i)

            try:

                if not el.is_visible():
                    continue

                text = (
                    el.inner_text(
                        timeout=300
                    )
                    .strip()
                )

                if (
                    norm(text)
                    == "moi nhat"
                ):

                    newest = el

                    break

            except Exception:
                continue

    # =========================================================================
    # Không tìm thấy
    # =========================================================================

    if newest is None:

        dump_debug(
            page,
            "sort_menu_not_found"
        )

        try:

            log(
                "  aria-expanded="
                + str(
                    btn.get_attribute(
                        "aria-expanded"
                    )
                )
            )

        except Exception:
            pass

        return False

    # =========================================================================
    # Click Mới nhất
    # =========================================================================

    try:

        newest.click(
            timeout=5000
        )

    except Exception:

        newest.click(
            timeout=5000,
            force=True
        )

    log(
        "  ✓ đã chọn Mới nhất"
    )

    # =========================================================================
    # Chờ button đổi thành Mới nhất
    # =========================================================================

    try:

        page.wait_for_function(
            """
            () => {

                const btn =
                    document.querySelector(
                        'button.HQzyZ'
                    );

                if (!btn) {
                    return false;
                }

                const label =
                    btn.getAttribute(
                        'aria-label'
                    )
                    ||
                    btn.innerText
                    ||
                    '';

                const normalized =
                    label
                        .normalize('NFD')
                        .replace(
                            /[\\u0300-\\u036f]/g,
                            ''
                        )
                        .toLowerCase();

                return (
                    normalized.includes(
                        'moi nhat'
                    )
                    ||
                    normalized.includes(
                        'newest'
                    )
                );
            }
            """,
            timeout=10000
        )

        log(
            "  ✓ Google Maps xác nhận: "
            "Mới nhất"
        )

    except PWTimeout:

        log(
            "  ! chưa xác nhận được "
            "label nút sau khi chọn"
        )

    # =========================================================================
    # Chờ list reload
    # =========================================================================

    try:

        page.wait_for_function(
            """
            old => {

                const c =
                    document.querySelector(
                        '[data-review-id]'
                    );

                return (
                    !!c
                    &&
                    c.getAttribute(
                        'data-review-id'
                    ) !== old
                );
            }
            """,
            arg=first_before,
            timeout=10000
        )

    except PWTimeout:
        pass

    try:

        page.wait_for_selector(
            CARD,
            timeout=10000
        )

    except PWTimeout:
        pass

    page.wait_for_timeout(
        700
    )

    return True


# ============================================================================
# FIND SCROLL CONTAINER
# ============================================================================

def find_scroll_container_js():

    return """
    () => {

        const card =
            document.querySelector(
                '[data-review-id]'
            );

        if (!card) {
            return null;
        }

        let el =
            card.parentElement;

        while (el) {

            const style =
                getComputedStyle(el);

            if (
                el.scrollHeight >
                    el.clientHeight + 20
                &&
                /(auto|scroll)/.test(
                    style.overflowY
                )
            ) {

                return {
                    found: true,
                    scrollTop: el.scrollTop,
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight
                };
            }

            el = el.parentElement;
        }

        return {
            found: false
        };
    }
    """


# ============================================================================
# SCROLL AND COLLECT
# ============================================================================

def scroll_and_collect(
    page,
    max_n: int
) -> list[dict]:

    def count_reviews() -> int:

        try:

            return page.evaluate(
                COUNT_JS
            )

        except Exception:

            return 0

    # =========================================================================
    # Initial
    # =========================================================================

    last = count_reviews()

    log(
        f"  review ban đầu: {last}"
    )

    if (
        max_n
        and last >= max_n
    ):

        log(
            f"  ✓ đã đủ "
            f"{last}/{max_n} review"
        )

        try:
            page.evaluate(
                EXPAND_JS
            )
        except Exception:
            pass

        page.wait_for_timeout(
            500
        )

        rows = page.evaluate(
            PARSE_JS
        )

        return rows[:max_n]

    # =========================================================================
    # Scroll loop
    # =========================================================================

    stagnant = 0
    iteration = 0

    MAX_STAGNANT = 8

    while True:

        iteration += 1

        # ---------------------------------------------------------------------
        # Đạt max
        # ---------------------------------------------------------------------

        if (
            max_n
            and last >= max_n
        ):

            log(
                f"  ✓ đạt "
                f"{last}/{max_n} review"
            )

            break

        # ---------------------------------------------------------------------
        # JS scroll container
        # ---------------------------------------------------------------------

        try:

            result = page.evaluate(
                """
                () => {

                    const card =
                        document.querySelector(
                            '[data-review-id]'
                        );

                    if (!card) {
                        return {
                            ok: false,
                            reason: "no-review-card"
                        };
                    }

                    let el =
                        card.parentElement;

                    while (el) {

                        const style =
                            getComputedStyle(el);

                        if (
                            el.scrollHeight >
                                el.clientHeight + 20
                            &&
                            /(auto|scroll)/.test(
                                style.overflowY
                            )
                        ) {

                            const before =
                                el.scrollTop;

                            el.scrollTop =
                                el.scrollHeight;

                            el.dispatchEvent(
                                new Event(
                                    "scroll",
                                    {
                                        bubbles: true
                                    }
                                )
                            );

                            return {
                                ok: true,
                                before,
                                after:
                                    el.scrollTop,
                                height:
                                    el.scrollHeight,
                                client:
                                    el.clientHeight
                            };
                        }

                        el =
                            el.parentElement;
                    }

                    return {
                        ok: false,
                        reason:
                            "scroll-container-not-found"
                    };
                }
                """
            )

            if result.get("ok"):

                log(
                    f"  scroll container: "
                    f"{result['before']} -> "
                    f"{result['after']} "
                    f"(height={result['height']})"
                )

            else:

                log(
                    "  ! không tìm thấy "
                    "scroll container: "
                    f"{result.get('reason')}"
                )

        except Exception as e:

            log(
                f"  ! lỗi scroll container: {e}"
            )

        # ---------------------------------------------------------------------
        # Chờ load
        # ---------------------------------------------------------------------

        delay = (
            GOOGLE_MAPS_REVIEWS_DELAY_SECONDS
            * random.uniform(
                0.8,
                1.5
            )
        )

        page.wait_for_timeout(
            int(
                delay * 1000
            )
        )

        now = count_reviews()

        log(
            f"  scroll #{iteration}: "
            f"{last} -> {now} review"
        )

        if now > last:

            last = now
            stagnant = 0

            continue

        # ---------------------------------------------------------------------
        # Mouse wheel
        # ---------------------------------------------------------------------

        try:

            card = page.locator(
                '[data-review-id]'
            ).last

            box = card.bounding_box()

            if box:

                x = (
                    box["x"]
                    + box["width"] / 2
                )

                y = (
                    box["y"]
                    + box["height"] / 2
                )

                page.mouse.move(
                    x,
                    y
                )

                page.mouse.wheel(
                    0,
                    1500
                )

        except Exception as e:

            log(
                f"  ! wheel scroll lỗi: {e}"
            )

        page.wait_for_timeout(
            int(
                GOOGLE_MAPS_REVIEWS_DELAY_SECONDS
                * random.uniform(
                    0.8,
                    1.5
                )
                * 1000
            )
        )

        now = count_reviews()

        log(
            f"  wheel #{iteration}: "
            f"{last} -> {now} review"
        )

        if now > last:

            last = now
            stagnant = 0

            continue

        # ---------------------------------------------------------------------
        # Thử scroll container thêm lần nữa
        # ---------------------------------------------------------------------

        try:

            page.evaluate(
                """
                () => {

                    const cards =
                        document.querySelectorAll(
                            '[data-review-id]'
                        );

                    if (!cards.length) {
                        return;
                    }

                    const lastCard =
                        cards[
                            cards.length - 1
                        ];

                    let el =
                        lastCard.parentElement;

                    while (el) {

                        if (
                            el.scrollHeight >
                            el.clientHeight + 50
                        ) {

                            el.scrollTop =
                                Math.min(
                                    el.scrollTop
                                    + el.clientHeight
                                    + 1000,
                                    el.scrollHeight
                                );

                            el.dispatchEvent(
                                new Event(
                                    "scroll",
                                    {
                                        bubbles: true
                                    }
                                )
                            );

                            return;
                        }

                        el =
                            el.parentElement;
                    }
                }
                """
            )

        except Exception:
            pass

        page.wait_for_timeout(
            1200
        )

        now = count_reviews()

        if now > last:

            last = now
            stagnant = 0

            continue

        # ---------------------------------------------------------------------
        # Stagnant
        # ---------------------------------------------------------------------

        stagnant += 1

        log(
            f"  ! chưa có review mới "
            f"({stagnant}/{MAX_STAGNANT})"
        )

        if stagnant >= MAX_STAGNANT:
            break

    # =========================================================================
    # Expand reviews
    # =========================================================================

    try:

        page.evaluate(
            EXPAND_JS
        )

    except Exception:
        pass

    page.wait_for_timeout(
        700
    )

    # =========================================================================
    # Parse
    # =========================================================================

    rows = page.evaluate(
        PARSE_JS
    )

    log(
        f"  đã tải {len(rows)} review"
        + (
            f" (yêu cầu {max_n})"
            if max_n
            else ""
        )
    )

    if (
        max_n
        and len(rows) < max_n
    ):

        log(
            f"  ! Google Maps chỉ "
            f"render được {len(rows)}/{max_n} "
            f"review trong phiên này"
        )

    return (
        rows[:max_n]
        if max_n
        else rows
    )


# ============================================================================
# CRAWL ONE PLACE
# ============================================================================

def crawl_review(
    page,
    place: dict,
    max_n: int
) -> dict:

    found_name = open_place(
        page,
        place
    )

    matched = name_matches(
        place["name"],
        found_name
    )

    if not matched:

        log(
            f'  !!! TÊN KHÔNG KHỚP: '
            f'cần "{place["name"]}" '
            f'nhưng Google đang mở '
            f'"{found_name}"'
        )

        # =====================================================================
        # Đây là lỗi nghiêm trọng.
        # Không crawl review của place sai.
        # =====================================================================

        raise RuntimeError(
            "Google Maps mở sai place. "
            f'cần="{place["name"]}", '
            f'found="{found_name}"'
        )

    url = page.url

    rows = []

    if open_reviews_tab(page):

        sort_ok = sort_by_newest(
            page
        )

        if not sort_ok:

            raise RuntimeError(
                "Không thể chuyển sang "
                "Mới nhất"
            )

        rows = scroll_and_collect(
            page,
            max_n
        )

    else:

        log(
            "  ! place chưa có review"
        )

    return {
        "found_name": found_name,
        "name_matched": matched,
        "url": url,
        "rows": rows,
    }


# ============================================================================
# CSV WRITE
# ============================================================================

def validate_csv_schema(
    path: Path
) -> None:

    if not path.exists():
        return

    if path.stat().st_size == 0:
        return

    with path.open(
        encoding="utf-8-sig",
        newline=""
    ) as f:

        reader = csv.DictReader(f)

        fieldnames = (
            reader.fieldnames
            or []
        )

    if fieldnames != FIELDS:

        raise RuntimeError(
            "Schema CSV không đúng.\n"
            f"File: {path}\n"
            f"Header hiện tại: "
            f"{fieldnames}\n"
            f"Header mong đợi: "
            f"{FIELDS}\n\n"
            "Hãy backup/xóa file CSV cũ "
            "bị sai header trước khi chạy lại."
        )


def sumary_review(
    place_id: str,
    rows: list[dict],
    out_path: Path,
    crawled_at: str
) -> int:

    out_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # =========================================================================
    # Validate trước
    # =========================================================================

    validate_csv_schema(
        out_path
    )

    existing = set()

    added = 0

    file_exists = out_path.exists()

    file_empty = (
        not file_exists
        or out_path.stat().st_size == 0
    )

    # =========================================================================
    # Đọc review_id đã tồn tại
    # =========================================================================

    if (
        file_exists
        and not file_empty
    ):

        with out_path.open(
            encoding="utf-8-sig",
            newline=""
        ) as f:

            reader = csv.DictReader(
                f
            )

            for row in reader:

                review_id = (
                    row.get(
                        "review_id"
                    )
                    or ""
                ).strip()

                if review_id:
                    existing.add(
                        review_id
                    )

    # =========================================================================
    # Append
    # =========================================================================

    with out_path.open(
        "a",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=FIELDS
        )

        # ---------------------------------------------------------------------
        # QUAN TRỌNG:
        # File mới / file rỗng => header ở row 1
        # ---------------------------------------------------------------------

        if file_empty:

            writer.writeheader()

            log(
                "  ✓ đã tạo CSV với header"
            )

        # ---------------------------------------------------------------------
        # Ghi review
        # ---------------------------------------------------------------------

        for r in rows:

            review_id = (
                r.get(
                    "review_id"
                )
                or ""
            ).strip()

            if not review_id:
                continue

            if review_id in existing:
                continue

            likes = (
                re.sub(
                    r"\D",
                    "",
                    r.get(
                        "likes_count"
                    )
                    or ""
                )
                or "0"
            )

            writer.writerow(
                {
                    "review_id":
                        review_id,

                    "place_id":
                        place_id,

                    "rating":
                        r.get(
                            "rating"
                        )
                        or "",

                    "review_text":
                        r.get(
                            "review_text"
                        )
                        or "",

                    "review_date":
                        r.get(
                            "review_date"
                        )
                        or "",

                    "likes_count":
                        likes,

                    "source":
                        "google_maps",

                    "crawled_at_utc":
                        crawled_at,
                }
            )

            existing.add(
                review_id
            )

            added += 1

    return added

# ============================================================================
# BRONZE JSONL WRITE
# ============================================================================

def append_bronze_review(
    path: Path,
    review: dict,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with path.open(
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            json.dumps(
                review,
                ensure_ascii=False,
                separators=(",", ":")
            )
            + "\n"
        )

# ============================================================================
# SAVE RESULT JSON
# ============================================================================


# ============================================================================
# MAIN
# ============================================================================

def main() -> None:

    ap = argparse.ArgumentParser(
        description=(
            "Crawl Google Maps reviews"
        )
    )

    ap.add_argument(
        "--limit",
        type=int,
        default=GOOGLE_MAPS_REVIEWS_LIMIT,
        help=(
            "số place "
            "(0 = tất cả)"
        )
    )

    ap.add_argument(
        "--max-reviews",
        type=int,
        default=MAX_REVIEWS_PER_PLACE,
        help=(
            "review/place "
            "(0 = hết)"
        )
    )

    ap.add_argument(
        "--headless",
        action="store_true",
        help=(
            "chạy ẩn"
        )
    )

    ap.add_argument(
        "--force",
        action="store_true",
        help=(
            "crawl lại place "
            "đã có trong CSV"
        )
    )

    ap.add_argument(
        "--name",
        help=(
            "test nhanh 1 place"
        )
    )

    ap.add_argument(
        "--province",
        default="",
        help=(
            "đi kèm --name"
        )
    )

    args = ap.parse_args()
    # =========================================================================
    # RUN / BRONZE OUTPUT
    # =========================================================================

    run_started_at = datetime.now(timezone.utc)

    run_id = (
        f"google_maps-"
        f"{run_started_at.strftime('%Y%m%dT%H%M%SZ')}-"
        f"{uuid.uuid4().hex[:12]}"
    )

    crawl_date = run_started_at.strftime(
        "%Y-%m-%d"
    )

    bronze_dir = (
        BRONZE_REVIEWS_DIR
        / f"crawl_date={crawl_date}"
    )

    bronze_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    bronze_file = (
        bronze_dir
        / f"part-{run_id}.jsonl"
    )

    log(
        f"[RUN] {run_id}"
    )

    log(
        f"[BRONZE] {bronze_file}"
    )

    # =========================================================================
    # Validate args
    # =========================================================================

    if args.max_reviews < 0:

        raise SystemExit(
            "--max-reviews phải >= 0"
        )

    # =========================================================================
    # Select places
    # =========================================================================

    if args.name:

        # =====================================================================
        # TEST MODE
        #
        # Không cache.
        # Không skip theo CSV.
        #
        # Cho phép chạy:
        #
        # --name A
        # --name A
        # --name A
        #
        # bao nhiêu lần cũng được.
        # =====================================================================

        places = [
            {
                "place_id": "TEST",
                "name": args.name,
                "province": args.province,
            }
        ]

        test_mode = True

    else:

        places = select_places(
            args.limit
        )

        test_mode = False

    # =========================================================================
    # DONE
    # =========================================================================

    if test_mode:

        # ---------------------------------------------------------------------
        # Test 1 place -> KHÔNG skip.
        # ---------------------------------------------------------------------

        todo = places

        log(
            "  [TEST MODE] "
            "không dùng URL cache"
        )

        log(
            "  [TEST MODE] "
            "không bỏ qua place "
            "đã crawl trước đó"
        )

    else:

        done = (
            set()
            if args.force
            else load_done_place_ids(
                REVIEWS_FILE
            )
        )

        todo = [
            p
            for p in places
            if (
                args.force
                or p["place_id"]
                not in done
            )
        ]

    log(
        f"{len(places)} place, "
        f"bỏ qua "
        f"{len(places) - len(todo)} "
        f"place đã crawl, "
        f"chạy {len(todo)} place"
    )

    # =========================================================================
    # RESULT
    # =========================================================================

    results = {

        "started_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(
                timespec="seconds"
            ),

        "config": {

            "max_reviews":
                args.max_reviews,

            "limit":
                args.limit,

            "headless":
                args.headless,

            "test_mode":
                test_mode,

            "url_cache":
                False,
        },

        "places": [],
    }

    # =========================================================================
    # PLAYWRIGHT
    # =========================================================================

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=args.headless
        )

        ctx = browser.new_context(

            locale="vi-VN",

            timezone_id=(
                "Asia/Ho_Chi_Minh"
            ),

            viewport={
                "width": 1366,
                "height": 900,
            },
        )

        try:

            for i, place in enumerate(
                todo,
                1
            ):

                t0 = time.time()

                log(
                    f'[{i}/{len(todo)}] '
                    f'{place["name"]} '
                    f'- '
                    f'{place["province"]}'
                )

                rec = {

                    "place_id":
                        place["place_id"],

                    "name":
                        place["name"],

                    "status":
                        "ok",

                    "found_name":
                        None,

                    "name_matched":
                        None,

                    "reviews_crawled":
                        0,

                    "new_rows":
                        0,

                    "url":
                        None,

                    "error":
                        None,
                }

                page = ctx.new_page()

                blocked = False

                try:

                    # =========================================================
                    # Crawl
                    # =========================================================

                    info = crawl_review(
                        page,
                        place,
                        args.max_reviews
                    )

                    crawled_at = (
                        datetime.now(
                            timezone.utc
                        ).isoformat(
                            timespec="seconds"
                        )
                    )
                    # =========================================================
                    # BRONZE JSONL
                    # =========================================================

                    bronze_count = 0

                    for review in info["rows"]:

                        bronze_record = {
                            "run_id": run_id,
                            "crawl_date": crawl_date,
                            "place_id": place["place_id"],
                            "place_name": place["name"],
                            "province": place["province"],
                            "source": "google_maps",
                            "crawled_at_utc": crawled_at,
                            **review,
                        }

                        append_bronze_review(
                            bronze_file,
                            bronze_record
                        )

                        bronze_count += 1


                    # =========================================================
                    # CSV
                    # =========================================================

                    added = sumary_review(
                        place[
                            "place_id"
                        ],
                        info[
                            "rows"
                        ],
                        REVIEWS_FILE,
                        crawled_at
                    )

                    rec.update(

                        found_name=
                            info[
                                "found_name"
                            ],

                        name_matched=
                            info[
                                "name_matched"
                            ],

                        url=
                            info[
                                "url"
                            ],

                        reviews_crawled=
                            len(
                                info[
                                    "rows"
                                ]
                            ),

                        new_rows=
                            added,
                        
                        bronze_rows=
                            bronze_count,
                    )

                    if not info["rows"]:

                        rec[
                            "status"
                        ] = "no_reviews"

                    log(
                        f"  -> "
                        f"{len(info['rows'])} "
                        f"review, "
                        f"ghi mới "
                        f"{added}"
                    )

                except BlockedError as e:

                    rec.update(

                        status="blocked",

                        error=str(e)
                    )

                    log(
                        f"  !!! {e} "
                        f"-> dừng"
                    )

                    dump_debug(
                        page,
                        f"blocked_{place['place_id']}"
                    )

                    blocked = True

                except Exception as e:

                    rec.update(

                        status="error",

                        error=(
                            f"{type(e).__name__}: "
                            f"{e}"
                        )[:1000]
                    )

                    log(
                        f"  !!! lỗi: "
                        f"{rec['error']}"
                    )

                    dump_debug(
                        page,
                        f"error_{place['place_id']}"
                    )

                finally:

                    page.close()

                # =============================================================
                # Timing
                # =============================================================

                rec["seconds"] = round(
                    time.time() - t0,
                    1
                )

                results[
                    "places"
                ].append(
                    rec
                )

   
                # =============================================================
                # Blocked -> stop
                # =============================================================

                if blocked:
                    break

                # =============================================================
                # Delay giữa place
                # =============================================================

                time.sleep(
                    GOOGLE_MAPS_DELAY_SECONDS
                    * random.uniform(
                        0.8,
                        1.6
                    )
                )

        finally:

            browser.close()

    # =========================================================================
    # FINAL RESULT
    # =========================================================================

    results[
        "finished_at_utc"
    ] = (
        datetime.now(
            timezone.utc
        ).isoformat(
            timespec="seconds"
        )
    )

    results[
        "total_new_rows"
    ] = sum(
        r[
            "new_rows"
        ]
        for r in results[
            "places"
        ]
    )

    log(
        "Xong. Tổng review mới: "
        f"{results['total_new_rows']} "
        f"-> {REVIEWS_FILE}"
    )


# ============================================================================
# ENTRY
# ============================================================================

if __name__ == "__main__":
    main()
