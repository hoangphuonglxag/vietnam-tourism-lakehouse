"""
Crawl review Google Maps theo:
place name + province
-> tab Bài đánh giá
-> Mới nhất
-> cuộn (wheel thật, không set scrollTop)
-> parse review
-> ghi CSV + bronze JSONL

Chạy thử 1 place:
    python tests/crawl_review.py --name "Công viên Nước Đầm Sen" --province "Hồ Chí Minh" --max-reviews 30

Chạy nhiều place:
    python tests/crawl_review.py --max-reviews 100
    python tests/crawl_review.py --limit 3 --max-reviews 100
    python tests/crawl_review.py --limit 3 --force --max-reviews 100
    python tests/crawl_review.py --limit 3 --headless

LƯU Ý QUAN TRỌNG (lý do sửa lần này):
    Google Maps chỉ tải thêm review khi nhận SỰ KIỆN WHEEL THẬT (do trình duyệt
    sinh ra khi cuộn chuột/chạm). Set `el.scrollTop = el.scrollHeight` bằng JS rồi
    tự bắn `dispatchEvent('scroll')` là sự kiện giả -> Google không lazy-load thêm,
    và vì nhảy thẳng lên đỉnh cuộn nên sau đó cũng không còn "khoảng" để cuộn tiếp.
    Vì vậy script này KHÔNG set scrollTop bằng JS nữa, chỉ dùng page.mouse.wheel()
    (sự kiện wheel thật qua CDP) đặt đúng vị trí giữa panel review.

Trong giai đoạn TEST, URL CACHE ĐÃ ĐƯỢC TẮT (mỗi lần chạy search lại từ đầu).
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

if hasattr(sys.stdout, "reconfigure"):          # tránh lỗi in tiếng Việt trên Windows
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
# CONFIG (đọc từ env, có mặc định)
# ============================================================================
GOOGLE_MAPS_REVIEWS_LIMIT = int(os.getenv("GOOGLE_MAPS_REVIEWS_LIMIT", "0"))     # số place, 0 = tất cả
MAX_REVIEWS_PER_PLACE = int(os.getenv("MAX_REVIEWS_PER_PLACE", "100"))           # 0 = lấy hết
GOOGLE_MAPS_DELAY_SECONDS = float(os.getenv("GOOGLE_MAPS_DELAY_SECONDS", "1.0"))                 # giữa 2 place
GOOGLE_MAPS_REVIEWS_DELAY_SECONDS = float(os.getenv("GOOGLE_MAPS_REVIEWS_DELAY_SECONDS", "1.0"))  # giữa 2 lần wheel

# Bao nhiêu lần wheel liên tiếp không tăng review thì coi là hết / bị chặn lazy-load
MAX_STAGNANT_WHEELS = 10

FIELDS = ["review_id", "place_id", "rating", "review_text",
          "review_date", "likes_count", "source", "crawled_at_utc"]
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
# SELECTORS / REGEX (Google hay đổi class -> nếu hỏng thì soi lại bằng DevTools)
# ============================================================================
CARD = "[data-review-id]"
RESULT_LINK = 'a.hfpxzc, div[role="feed"] a[href*="/maps/place/"]'

TAB_RE = re.compile(r"Bài đánh giá|Đánh giá|Reviews?", re.I)
SORT_BTN_RE = re.compile(
    r"Sắp xếp|Sort|Phù hợp nhất|Most relevant|Mới nhất|Newest|Cao nhất|Highest|Thấp nhất|Lowest", re.I)
NEWEST_RE = re.compile(r"^Mới nhất|^Newest", re.I)
NO_RESULT_RE = re.compile(r"không thể tìm thấy|không tìm thấy|can't find|couldn't find", re.I)
TOTAL_REVIEWS_RE = re.compile(r"([\d.,]+)\s*(?:bài đánh giá|đánh giá|reviews?)", re.I)

COUNT_JS = ("() => new Set([...document.querySelectorAll('[data-review-id]')]"
            ".map(e => e.getAttribute('data-review-id'))).size")

FIRST_ID_JS = ("() => document.querySelector('[data-review-id]')"
               "?.getAttribute('data-review-id') || ''")

TAB_SELECTED_JS = r"""
() => [...document.querySelectorAll('button[role="tab"]')].some(t =>
  t.getAttribute('aria-selected') === 'true' &&
  /Bài đánh giá|Đánh giá|Reviews?/i.test((t.getAttribute('aria-label') || '') + ' ' + t.innerText))
"""

EXPAND_JS = """
() => {
    const buttons = document.querySelectorAll(
        '[data-review-id] button.w8nwRe, ' +
        '[data-review-id] button[aria-label="Xem thêm"], ' +
        '[data-review-id] button[aria-label="See more"]'
    );

    for (const b of buttons) {
        try {
            b.click();
        } catch (e) {}
    }

    return buttons.length;
}
"""


# Tìm khung chứa review để lấy toạ độ đặt chuột vào rồi wheel thật.
# Ưu tiên div[role="main"] (panel chính bên phải), vì Maps thường không tách
# riêng một khung cuộn chỉ cho phần review. Fallback: khung cuộn được lớn nhất
# có chứa review card.
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
        const s = getComputedStyle(el);

        if (
            el.scrollHeight > el.clientHeight + 20 &&
            /(auto|scroll)/.test(s.overflowY)
        ) {
            const r = el.getBoundingClientRect();

            return {
                ok: true,
                why: 'review-card-ancestor',
                rect: {
                    x: r.x,
                    y: r.y,
                    width: r.width,
                    height: r.height
                },
                scrollTop: el.scrollTop,
                scrollHeight: el.scrollHeight,
                clientHeight: el.clientHeight,
                overflowY: s.overflowY,
                tag: el.tagName,
                role: el.getAttribute('role'),
                cls: (el.className || '').toString().slice(0, 120)
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
  document.querySelectorAll('[data-review-id]').forEach(e => {
    const id = e.getAttribute('data-review-id');
    if (id && !seen.has(id)) seen.set(id, e);
  });
  return [...seen.entries()].map(([id, c]) => {
    const q = s => c.querySelector(s);
    const star = (q('span.kvMYJc') || q('[role="img"][aria-label]'))?.getAttribute('aria-label') || '';
    const textEl = [...c.querySelectorAll('span.wiI7pd')].find(e => !e.closest('.CDe7pd'));
    return {
      review_id: id,
      rating: (star.match(/\d+/) || [null])[0],
      review_text: (textEl?.innerText || '').trim(),
      review_date: (q('span.rsqaWe')?.innerText || '').trim(),
      likes_count: (q('span.pkWtMe')?.innerText || '0').trim(),
    };
  });
}
"""


class BlockedError(Exception):
    """Google chặn / hiện CAPTCHA -> dừng cả lượt chạy."""


class PlaceNotFound(Exception):
    """Search không ra địa điểm nào."""


class NoReviewsTab(Exception):
    """Trang place không có tab đánh giá."""


def log(msg: str) -> None:
    print(msg, flush=True)


# ============================================================================
# Chuẩn hoá / so khớp tên
# ============================================================================
def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", s).split())


def name_matches(wanted: str, found: str) -> bool:
    a, b = norm(wanted), norm(found)
    if not a or not b:
        return True
    if a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.6


def log_scroll_candidates(page) -> None:
    try:
        cands = page.evaluate(LIST_SCROLL_CANDIDATES_JS)
    except Exception:
        return
    for d in cands:
        log(f"  [cand] tag={d['tag']} role={d['role']} cls={d['cls']!r} "
            f"scrollH={d['scrollHeight']} clientH={d['clientHeight']} "
            f"reviewCards={d['reviewCards']}")


def check_blocked(page) -> None:
    if "/sorry/" in page.url or page.locator('iframe[src*="recaptcha"]').count() > 0:
        raise BlockedError(f"Bị chặn / CAPTCHA: {page.url}")


def handle_consent(page) -> None:
    if "consent.google" not in page.url:
        return
    try:
        page.get_by_role(
            "button", name=re.compile(r"Chấp nhận tất cả|Accept all|Từ chối tất cả|Reject all", re.I)
        ).first.click(timeout=5000)
    except Exception:
        pass
    try:
        page.wait_for_url(re.compile(r"google\.[a-z.]+/maps"), timeout=15000)
    except PWTimeout:
        pass


# ============================================================================
# Đọc danh sách place
# ============================================================================
def _pick(row: dict, *keys: str) -> str:
    for k in keys:
        v = row.get(k)
        if v and v.strip():
            return v.strip()
    return ""


def select_places(limit: int = 0) -> list[dict]:
    if not PLACES_FILE.exists():
        raise RuntimeError(f"Không tìm thấy places.csv: {PLACES_FILE}")
    places: list[dict] = []
    with PLACES_FILE.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = _pick(row, "place_name", "name", "place", "title")
            if not name:
                continue
            places.append({
                "place_id": _pick(row, "place_id", "id"),
                "name": name,
                "province": _pick(row, "province_name", "province", "city"),
            })
    return places[:limit] if limit else places


def load_place_status(path: Path) -> dict[str, str]:
    """place_id -> status từ file status crawl review."""
    if not path.exists():
        return {}

    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            if "place_id" not in (reader.fieldnames or []):
                return {}

            return {
                row["place_id"]: row.get("status", "")
                for row in reader
                if row.get("place_id")
            }

    except Exception:
        return {}
    """place_id -> status ('success'/'partial'/'error') lấy từ lần chạy CSV kết quả gần nhất, nếu có cột đó."""
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if "place_id" not in (reader.fieldnames or []):
                return {}
            return {row["place_id"]: row.get("status", "") for row in reader if row.get("place_id")}
    except Exception:
        return {}


# ============================================================================
# Mở place: search -> chọn kết quả khớp tên -> vào trang place
# ============================================================================
def open_place(page, place: dict) -> str:
    query = f'{place["name"]} {place["province"]}'.strip()
    search_url = f"https://www.google.com/maps/search/{quote(query)}?hl=vi"
    log(f"  → search: {query}")

    page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    handle_consent(page)
    check_blocked(page)
    page.wait_for_timeout(2500)          # Maps còn render/redirect sau domcontentloaded

    if "/maps/place/" not in page.url:
        try:
            page.wait_for_function(
                "() => location.href.includes('/maps/place/') "
                "|| document.querySelectorAll('a.hfpxzc').length > 0 "
                "|| /không thể tìm thấy|không tìm thấy|can.t find/i.test(document.body.innerText)",
                timeout=15000)
        except PWTimeout:
            pass

        if page.get_by_text(NO_RESULT_RE).count() > 0:
            raise PlaceNotFound(f'Search không ra kết quả: "{query}"')

        if "/maps/place/" not in page.url:
            raise RuntimeError(f"Không mở được trang place. url={page.url}")

        log(f"  ✓ đã vào place: {page.url}")
        check_blocked(page)

        # Google Maps đôi khi render place lần đầu chưa đầy đủ tab/UI.
        # Chủ động reload MỘT lần sau khi chắc chắn đã vào /maps/place/.
        log("  → chờ Google Maps UI ổn định trước khi reload")
        page.wait_for_timeout(3000)

        log("  → RELOAD trang place")
        page.reload(wait_until="domcontentloaded", timeout=30000)

        handle_consent(page)
        check_blocked(page)

        log("  → chờ UI sau reload")
        page.wait_for_timeout(5000)


    try:
        page.locator("h1.DUwDvf").first.wait_for(state="visible", timeout=15000)
    except PWTimeout:
        log("  ! chưa thấy h1.DUwDvf, tiếp tục")

    found_name = ""
    try:
        found_name = page.locator("h1.DUwDvf").first.inner_text(timeout=5000).strip()
    except Exception:
        pass
    if not found_name:
        found_name = page.title().replace(" - Google Maps", "").strip()

    if found_name:
        log(f'  ✓ place hiện tại: "{found_name}"')
    return found_name


# ============================================================================
# Mở tab Bài đánh giá
# ============================================================================
def open_reviews_tab(page) -> bool:
    for attempt in range(1, 4):
        log(f"  → tìm tab Bài đánh giá (lần {attempt}/3)")
        tab = page.get_by_role("tab", name=TAB_RE).first
        try:
            tab.wait_for(state="visible", timeout=5000)
        except PWTimeout:
            page.wait_for_timeout(1000 * attempt)
            continue

        tab.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        try:
            tab.click(timeout=5000)
        except PWTimeout:
            continue

        try:
            page.wait_for_function(TAB_SELECTED_JS, timeout=5000)
        except PWTimeout:
            log("  ! không xác nhận được aria-selected, thử đi tiếp")

        try:
            page.wait_for_selector(CARD, timeout=8000)
            log("  ✓ review đã render")
            return True
        except PWTimeout:
            log("  ! đã click tab nhưng review chưa render")
            page.wait_for_timeout(1000 * attempt)

    tabs = []
    try:
        tabs = page.locator('button[role="tab"]').all_inner_texts()
    except Exception:
        pass
    log(f"  !!! không mở được tab Bài đánh giá. tabs={tabs}")
    return False


# ============================================================================
# Sắp xếp Mới nhất
# ============================================================================
def sort_by_newest(page) -> bool:
    log("  → tìm nút sắp xếp")

    btn = page.locator("button.HQzyZ").first

    try:
        btn.wait_for(state="visible", timeout=10000)
    except PWTimeout:
        btn = page.get_by_role(
            "button",
            name=SORT_BTN_RE
        ).first

        try:
            btn.wait_for(state="visible", timeout=8000)
        except PWTimeout:
            log("  !!! không thấy nút sắp xếp")
            return False

    current = (
        btn.get_attribute("aria-label")
        or btn.inner_text()
        or ""
    ).strip()

    log(f"  nút sắp xếp hiện tại: {current!r}")

    # Nếu đã ở chế độ Mới nhất
    if "moi nhat" in norm(current) or "newest" in norm(current).lower():
        log("  ✓ đã ở chế độ Mới nhất")
        return True

    log("  → click nút sắp xếp")

    try:
        btn.click(timeout=5000)
    except Exception as e:
        log(f"  !!! không click được nút sắp xếp: {e}")
        return False

    page.wait_for_timeout(1000)

    # ------------------------------------------------------------------------
    # Debug: đọc text thực tế của menu Google Maps
    # ------------------------------------------------------------------------
    log("  → kiểm tra menu sắp xếp")

    try:
        texts = page.locator(
            '[role="menu"], '
            '[role="listbox"], '
            '[role="dialog"], '
            '[role="menuitem"], '
            '[role="option"]'
        ).all_inner_texts()

        for t in texts:
            t = t.strip()
            if t:
                log(f"    [sort-option] {t!r}")

    except Exception as e:
        log(f"  ! không đọc được menu: {e}")

    # ------------------------------------------------------------------------
    # Tìm "Mới nhất"
    #
    # Google Maps hiện tại có thể trả về:
    #     Mới nhất
    #
    # hoặc:
    #     Mới nhất
    #
    # (dấu bị tách thành Unicode combining character).
    #
    # Vì vậy KHÔNG dùng regex "^Mới nhất$".
    # Dùng norm() để chuẩn hóa Unicode rồi so sánh.
    # ------------------------------------------------------------------------
    newest = None

    try:
        candidates = page.locator(
            '[role="menuitem"], '
            '[role="menuitemradio"], '
            '[role="option"], '
            '[role="button"]'
        )

        count = candidates.count()

        for i in range(count):
            el = candidates.nth(i)

            try:
                text = el.inner_text(timeout=500).strip()
            except Exception:
                continue

            if norm(text) == "moi nhat":
                newest = el
                log(f"  ✓ tìm thấy option 'Mới nhất': {text!r}")
                break

    except Exception as e:
        log(f"  ! lỗi khi tìm option Mới nhất: {e}")

    # ------------------------------------------------------------------------
    # Fallback:
    # Một số phiên bản Google Maps không gắn role menuitem/menuitemradio
    # cho option. Tìm theo text rộng rồi dùng norm() kiểm tra.
    # ------------------------------------------------------------------------
    if newest is None:
        try:
            candidates = page.get_by_text(
                re.compile(r"Mới|Newest|Mới", re.I)
            )

            count = candidates.count()

            for i in range(count):
                el = candidates.nth(i)

                try:
                    text = el.inner_text(timeout=500).strip()
                except Exception:
                    continue

                if norm(text) == "moi nhat":
                    newest = el
                    log(f"  ✓ tìm thấy option 'Mới nhất' (fallback): {text!r}")
                    break

        except Exception as e:
            log(f"  ! fallback tìm Mới nhất lỗi: {e}")

    # ------------------------------------------------------------------------
    # Không tìm thấy -> FAIL, tuyệt đối không crawl tiếp
    # ------------------------------------------------------------------------
    if newest is None:
        log("  !!! KHÔNG TÌM THẤY 'Mới nhất'")
        return False

    # ------------------------------------------------------------------------
    # Click Mới nhất
    # ------------------------------------------------------------------------
    try:
        newest.click(timeout=5000)
    except Exception:
        try:
            newest.click(timeout=5000, force=True)
        except Exception as e:
            log(f"  !!! không click được 'Mới nhất': {e}")
            return False

    log("  ✓ đã click 'Mới nhất'")

    # Chờ Google Maps cập nhật danh sách review
    page.wait_for_timeout(1500)

    # ------------------------------------------------------------------------
    # Xác nhận lại trạng thái sort
    # ------------------------------------------------------------------------
    try:
        after = (
            btn.get_attribute("aria-label")
            or btn.inner_text()
            or ""
        ).strip()
    except Exception:
        after = ""

    log(f"  nút sắp xếp sau khi chọn: {after!r}")

    if "moi nhat" in norm(after) or "newest" in norm(after).lower():
        log("  ✓✓ Google Maps đã xác nhận: Mới nhất")
        return True

    # Fallback xác nhận bằng các element có text "Mới nhất"
    try:
        selected_candidates = page.locator(
            '[aria-selected="true"], '
            '[aria-checked="true"], '
            '[role="menuitemradio"]'
        )

        for i in range(selected_candidates.count()):
            el = selected_candidates.nth(i)

            try:
                text = el.inner_text(timeout=500).strip()
            except Exception:
                continue

            if norm(text) == "moi nhat":
                log(
                    f"  ✓✓ Google Maps xác nhận Mới nhất "
                    f"qua selected element: {text!r}"
                )
                return True

    except Exception:
        pass

    log("  !!! chưa xác nhận được Google Maps đang ở Mới nhất")
    return False

    log("  → tìm nút sắp xếp")

    btn = page.locator("button.HQzyZ").first

    try:
        btn.wait_for(state="visible", timeout=10000)
    except PWTimeout:
        btn = page.get_by_role(
            "button",
            name=SORT_BTN_RE
        ).first

        try:
            btn.wait_for(state="visible", timeout=8000)
        except PWTimeout:
            log("  !!! không thấy nút sắp xếp")
            return False

    current = (
        btn.get_attribute("aria-label")
        or btn.inner_text()
        or ""
    ).strip()

    log(f"  nút sắp xếp hiện tại: {current!r}")

    # Nếu đã là Mới nhất
    if "moi nhat" in norm(current) or "newest" in norm(current):
        log("  ✓ đã ở chế độ Mới nhất")
        return True

    log("  → click nút sắp xếp")

    try:
        btn.click(timeout=5000)
    except Exception as e:
        log(f"  !!! không click được nút sắp xếp: {e}")
        return False

    page.wait_for_timeout(1000)

    # DEBUG: lấy text thực tế của menu Google Maps
    log("  → kiểm tra menu sắp xếp")

    try:
        texts = page.locator(
            '[role="menu"], '
            '[role="listbox"], '
            '[role="dialog"], '
            '[role="menuitem"], '
            '[role="option"]'
        ).all_inner_texts()

        for t in texts:
            t = t.strip()
            if t:
                log(f"    [sort-option] {t!r}")

    except Exception as e:
        log(f"  ! không đọc được menu: {e}")

    # Tìm Mới nhất bằng text thực tế, không ép role
    newest = page.get_by_text(
        re.compile(r"^\s*(Mới nhất|Newest)\s*$", re.I)
    ).last

    try:
        newest.wait_for(state="visible", timeout=5000)
    except PWTimeout:
        log("  !!! KHÔNG TÌM THẤY 'Mới nhất'")
        return False

    log("  ✓ đã thấy option 'Mới nhất'")

    try:
        newest.click(timeout=5000)
    except Exception:
        try:
            newest.click(timeout=5000, force=True)
        except Exception as e:
            log(f"  !!! không click được 'Mới nhất': {e}")
            return False

    page.wait_for_timeout(1500)

    # Xác nhận lại nút sort
    try:
        after = (
            btn.get_attribute("aria-label")
            or btn.inner_text()
            or ""
        ).strip()
    except Exception:
        after = ""

    log(f"  nút sắp xếp sau khi chọn: {after!r}")

    if "moi nhat" in norm(after) or "newest" in norm(after):
        log("  ✓✓ Google Maps đã xác nhận: Mới nhất")
        return True

    # Một số UI không cập nhật aria-label nhưng menu đã đóng.
    # Kiểm tra các text/aria hiện tại.
    try:
        body_text = page.locator("body").inner_text(timeout=3000)

        # Không dùng body text để kết luận tuyệt đối.
        # Chỉ log để debug.
        if re.search(r"\bMới nhất\b|\bNewest\b", body_text, re.I):
            log("  ! thấy 'Mới nhất' trong UI nhưng chưa xác nhận được nút")
    except Exception:
        pass

    log("  !!! chưa xác nhận được Google Maps đang ở Mới nhất")
    return False
    btn = page.locator("button.HQzyZ").first
    try:
        btn.wait_for(state="visible", timeout=10000)
    except PWTimeout:
        btn = page.get_by_role("button", name=SORT_BTN_RE).first
        try:
            btn.wait_for(state="visible", timeout=8000)
        except PWTimeout:
            log("  ! không thấy nút sắp xếp, dùng thứ tự mặc định")
            return False

    current = (btn.get_attribute("aria-label") or btn.inner_text() or "").strip()
    log(f"  nút sắp xếp ban đầu: {current!r}")
    if "moi nhat" in norm(current) or "newest" in norm(current):
        log("  ✓ đã ở chế độ Mới nhất")
        return True

    first_before = page.evaluate(FIRST_ID_JS)
    try:
        btn.click(timeout=5000)
    except Exception as e:
        log(f"  ! không click được nút sắp xếp: {e}")
        return False
    page.wait_for_timeout(400)

    newest = None
    try:
        newest = page.get_by_role(
            "menuitemradio",
            name=re.compile(r"Mới nhất|Newest", re.I)
        ).first
        newest.wait_for(state="visible", timeout=4000)
    except Exception:
        newest = None
    if newest is None:
        try:
            newest = page.get_by_text(
                re.compile(r"^\s*Mới nhất\s*$|^\s*Newest\s*$", re.I)
            ).last
            newest.wait_for(state="visible", timeout=3000)
        except Exception:
            newest = None
    if newest is None:
        log("  ! không tìm thấy option 'Mới nhất'")
        return False

    try:
        newest.click(timeout=5000)
    except Exception:
        newest.click(timeout=5000, force=True)
    log("  ✓ đã chọn Mới nhất")

    try:
        page.wait_for_function(
            "old => { const c = document.querySelector('[data-review-id]');"
            " return !!c && c.getAttribute('data-review-id') !== old; }",
            arg=first_before, timeout=8000)
    except PWTimeout:
        pass
    try:
        page.wait_for_selector(CARD, timeout=8000)
    except PWTimeout:
        pass
    page.wait_for_timeout(500)
    return True


# ============================================================================
# Tổng số review Google hiển thị (để tính success/partial)
# ============================================================================
def get_total_review_count(page) -> int | None:
    candidates = [
        "div.F7nice", "span.F7nice",
        'button[jsaction*="reviewChart"]',
    ]
    text = ""
    for sel in candidates:
        try:
            text = page.locator(sel).first.inner_text(timeout=2000)
            if text:
                break
        except Exception:
            continue
    if not text:
        try:
            text = page.locator("h1.DUwDvf").first.locator("xpath=../..").inner_text(timeout=2000)
        except Exception:
            return None
    m = TOTAL_REVIEWS_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(".", "").replace(",", ""))
    except ValueError:
        return None


# ============================================================================
# Cuộn bằng wheel THẬT (không set scrollTop) + parse
# ============================================================================
def locate_panel_center(page) -> tuple[float, float] | None:
    try:
        info = page.evaluate(FIND_PANEL_RECT_JS)
    except Exception as e:
        log(f"  ! lỗi tìm panel: {e}")
        return None

    if not info or not info.get("ok"):
        log(f"  ! không tìm được panel review: {info}")
        return None

    r = info["rect"]

    log(
        "  panel review: "
        f"tag={info.get('tag')} "
        f"role={info.get('role')} "
        f"overflowY={info.get('overflowY')} "
        f"scrollTop={info.get('scrollTop')} "
        f"scrollH={info.get('scrollHeight')} "
        f"clientH={info.get('clientHeight')}"
    )

    x = r["x"] + r["width"] / 2
    y = r["y"] + max(r["height"] * 0.4, 100)

    return x, y
    info = page.evaluate(FIND_PANEL_RECT_JS)
    if not info or not info.get("ok"):
        return None
    r = info["rect"]
    log(f"  panel cuộn: {info['why']} scrollH={r['scrollHeight']} clientH={r['clientHeight']}")
    # đặt chuột hơi lệch lên trên tâm để chắc chắn nằm trong panel (tránh mép dưới bị footer che)
    x = r["x"] + r["width"] / 2
    y = r["y"] + max(r["height"] * 0.4, 100)
    return x, y
def get_scroll_debug(page) -> dict | None:
    try:
        info = page.evaluate(FIND_PANEL_RECT_JS)
    except Exception:
        return None

    if not info or not info.get("ok"):
        return None

    return {
        "scrollTop": info.get("scrollTop"),
        "scrollHeight": info.get("scrollHeight"),
        "clientHeight": info.get("clientHeight"),
        "tag": info.get("tag"),
        "role": info.get("role"),
        "cls": info.get("cls"),
    }


def scroll_and_collect(page, max_n: int, debug: bool = False) -> list[dict]:
    def count_reviews() -> int:
        try:
            return page.evaluate(COUNT_JS)
        except Exception:
            return 0

    last = count_reviews()
    log(f"  review ban đầu: {last}")

    if max_n and last >= max_n:
        page.evaluate(EXPAND_JS)
        page.wait_for_timeout(500)
        return page.evaluate(PARSE_JS)[:max_n]

    point = locate_panel_center(page)
    if point is None:
        log("  ! không tìm được panel cuộn")
        if debug:
            log_scroll_candidates(page)
    else:
        x, y = point
        page.mouse.move(x, y)

    stagnant = 0
    i = 0
    while not (max_n and last >= max_n):
        i += 1

        # Tìm lại review panel ở MỖI vòng.
        point = locate_panel_center(page)

        before_scroll = get_scroll_debug(page)
        before_count = count_reviews()

        log(f"  wheel #{i} BEFORE:")
        if before_scroll:
            log(
                f"    scrollTop={before_scroll['scrollTop']} "
                f"scrollH={before_scroll['scrollHeight']} "
                f"clientH={before_scroll['clientHeight']}"
            )
        else:
            log("    không đọc được scroll state")

        log(f"    reviews={before_count}")

        if point is not None:
            x, y = point

            # Đặt chuột chính giữa vùng review.
            page.mouse.move(x, y)

            # Wheel nhỏ hơn để xem từng bước rõ ràng.
            page.mouse.wheel(0, 500)
        else:
            log("  ! không có review panel -> fallback keyboard End")
            page.keyboard.press("End")

        page.wait_for_timeout(
            int(
                1000
                * GOOGLE_MAPS_REVIEWS_DELAY_SECONDS
                * random.uniform(0.8, 1.5)
            )
        )

        after_scroll = get_scroll_debug(page)
        now = count_reviews()

        log(f"  wheel #{i} AFTER:")
        if after_scroll:
            log(
                f"    scrollTop={after_scroll['scrollTop']} "
                f"scrollH={after_scroll['scrollHeight']} "
                f"clientH={after_scroll['clientHeight']}"
            )
        else:
            log("    không đọc được scroll state")

        log(f"    reviews={now}")

        if before_scroll and after_scroll:
            top_before = before_scroll["scrollTop"]
            top_after = after_scroll["scrollTop"]

            if top_after == top_before:
                log("    !!! SCROLL TOP KHÔNG ĐỔI")
            else:
                log(f"    ✓ scrollTop thay đổi: {top_before} -> {top_after}")

        if now > last:
            last = now
            stagnant = 0
            log(f"    ✓ có review mới: {before_count} -> {now}")
        else:
            stagnant += 1
            log(f"    ! chưa có review mới ({stagnant}/{MAX_STAGNANT_WHEELS})")

            if stagnant >= MAX_STAGNANT_WHEELS:
                log(
                    f"  dừng cuộn: {stagnant} lần liên tiếp "
                    "không có review mới"
                )
                break


    page.evaluate(EXPAND_JS)
    page.wait_for_timeout(500)
    rows = page.evaluate(PARSE_JS)
    log(f"  đã tải {len(rows)} review" + (f" (yêu cầu {max_n})" if max_n else ""))
    return rows[:max_n] if max_n else rows


# ============================================================================
# Crawl 1 place
# ============================================================================
def crawl_review(page, place: dict, max_n: int, debug: bool = False) -> dict:
    tag = re.sub(r"\W+", "_", place["place_id"] or place["name"])

    found_name = open_place(page, place)
    matched = name_matches(place["name"], found_name)
    if not matched:
        log(f'  !!! tên không khớp: cần "{place["name"]}" nhưng ra "{found_name}"')
    url = page.url
    if not open_reviews_tab(page):

        raise NoReviewsTab(f"Không mở được tab Bài đánh giá: {url}")
    if not sort_by_newest(page):
        raise RuntimeError(
            "Không   thể xác nhận Google Maps đang ở chế độ 'Mới nhất'."
        )

    total = get_total_review_count(page)

    log(f"  tổng review Google hiển thị: {total}")

    rows = scroll_and_collect(page, max_n, debug)

    if not rows:
        raise RuntimeError("Đã mở được tab Bài đánh giá nhưng không lấy được review nào.")

    if max_n and len(rows) >= max_n:
        status = "success"
    elif total is not None and len(rows) >= total:
        status = "success"
    else:
        status = "partial"


    return {"found_name": found_name, "name_matched": matched, "url": url,
            "rows": rows, "total_reviews": total, "status": status}


# ============================================================================
# Ghi CSV
# ============================================================================
def validate_csv_schema(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open(encoding="utf-8-sig", newline="") as f:
        fieldnames = csv.DictReader(f).fieldnames or []
    if fieldnames != FIELDS:
        raise RuntimeError(
            f"Schema CSV không đúng.\nFile: {path}\nHeader hiện tại: {fieldnames}\n"
            f"Header mong đợi: {FIELDS}\nHãy backup/xóa file CSV cũ trước khi chạy lại.")


def sumary_review(place_id: str, rows: list[dict], out_path: Path, crawled_at: str) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    validate_csv_schema(out_path)

    existing: set[str] = set()
    file_exists = out_path.exists()
    file_empty = not file_exists or out_path.stat().st_size == 0
    if file_exists and not file_empty:
        with out_path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                rid = (row.get("review_id") or "").strip()
                if rid:
                    existing.add(rid)

    added = 0
    with out_path.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if file_empty:
            w.writeheader()
        for r in rows:
            rid = (r.get("review_id") or "").strip()
            if not rid or rid in existing:
                continue
            w.writerow({
                "review_id": rid,
                "place_id": place_id,
                "rating": r.get("rating") or "",
                "review_text": r.get("review_text") or "",
                "review_date": r.get("review_date") or "",
                "likes_count": re.sub(r"\D", "", r.get("likes_count") or "") or "0",
                "source": "google_maps",
                "crawled_at_utc": crawled_at,
            })
            existing.add(rid)
            added += 1
    return added


def append_bronze_review(path: Path, review: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(review, ensure_ascii=False, separators=(",", ":")) + "\n")

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
    error_message: str = "",
    crawled_at: str,
) -> None:
    """
    Upsert trạng thái crawl review theo place_id.

    Mỗi place chỉ giữ trạng thái mới nhất.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []

    if path.exists() and path.stat().st_size > 0:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
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

    tmp = path.with_suffix(".tmp")

    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=REVIEW_STATUS_FIELDS,
        )
        writer.writeheader()
        writer.writerows(rows)

    tmp.replace(path)

# ============================================================================
# main
# ============================================================================
def main() -> None:
    ap = argparse.ArgumentParser(description="Crawl Google Maps reviews")
    ap.add_argument("--limit", type=int, default=GOOGLE_MAPS_REVIEWS_LIMIT, help="số place (0 = tất cả)")
    ap.add_argument("--max-reviews", type=int, default=MAX_REVIEWS_PER_PLACE, help="review/place (0 = hết)")
    ap.add_argument("--headless", action="store_true", help="chạy ẩn")
    ap.add_argument("--force", action="store_true", help="crawl lại place đã có trong CSV, kể cả status success")
    ap.add_argument("--debug", action="store_true", help="lưu screenshot/html + liệt kê ứng viên cuộn")
    ap.add_argument("--name", help="test nhanh 1 place, không cần places.csv")
    ap.add_argument("--province", default="", help="đi kèm --name")
    ap.add_argument(
    "--new-only",
    action="store_true",
    help="chỉ crawl place chưa có status"
    )

    args = ap.parse_args()

    if args.max_reviews < 0:
        raise SystemExit("--max-reviews phải >= 0")

    run_started_at = datetime.now(timezone.utc)
    run_id = f"google_maps-{run_started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"
    crawl_date = run_started_at.strftime("%Y-%m-%d")
    bronze_dir = BRONZE_REVIEWS_DIR / f"crawl_date={crawl_date}"
    bronze_file = bronze_dir / f"part-{run_id}.jsonl"
    log(f"[RUN] {run_id}")
    log(f"[BRONZE] {bronze_file}")

    test_mode = bool(args.name)
    if test_mode:
        places = [{"place_id": "TEST", "name": args.name, "province": args.province}]
        log("  [TEST MODE] không dùng URL cache, không bỏ qua place đã crawl trước đó")
        todo = places
    else:
        places = select_places(args.limit)
        # bỏ qua place đã "success" ở lần chạy trước, trừ khi --force;
        # place "partial"/"error" luôn được crawl lại để lấy cho đủ.

        status_map = {} if args.force else load_place_status(REVIEW_STATUS_FILE)

        if args.new_only:
            todo = [
                p for p in places
                if p["place_id"] not in status_map
            ]
        else:
            todo = [
                p for p in places
                if args.force or status_map.get(p["place_id"]) != "success"
            ]

    log(f"{len(places)} place, bỏ qua {len(places) - len(todo)} place đã crawl đủ (success), "
        f"chạy {len(todo)} place")

    summary = {"success": 0, "partial": 0, "error": 0, "blocked": 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        ctx = browser.new_context(locale="vi-VN", timezone_id="Asia/Ho_Chi_Minh",
                                  viewport={"width": 1366, "height": 900})
        try:
            for i, place in enumerate(todo, 1):
                t0 = time.time()
                log(f'[{i}/{len(todo)}] {place["name"]} - {place["province"]}')
                page = ctx.new_page()
                blocked = False
                status = "error"
                try:
                    info = crawl_review(page, place, args.max_reviews, args.debug)

                    crawled_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    status = info["status"]

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


                    for review in info["rows"]:
                        append_bronze_review(bronze_file, {
                            "run_id": run_id, "crawl_date": crawl_date,
                            "place_id": place["place_id"], "place_name": place["name"],
                            "province": place["province"], "source": "google_maps",
                            "crawled_at_utc": crawled_at, "status": status,
                            "total_reviews": info["total_reviews"], **review,
                        })

                    added = sumary_review(place["place_id"], info["rows"], REVIEWS_FILE, crawled_at)
                    log(f"  -> {len(info['rows'])} review (tổng Google: {info['total_reviews']}), "
                        f"ghi mới {added}, status={status}")

                except BlockedError as e:
                    status = "blocked"
                    log(f"  !!! {e} -> dừng")
                    blocked = True
                except PlaceNotFound as e:
                    status = "error"
                    log(f"  !!! {e}")
                except NoReviewsTab as e:
                    status = "error"
                    log(f"  !!! {e}")
                except Exception as e:
                    status = "error"
                    log(f"  !!! lỗi: {type(e).__name__}: {e}")
                finally:
                    page.close()

                summary[status] = summary.get(status, 0) + 1
                log(f"  ({round(time.time() - t0, 1)}s)")
                if blocked:
                    break
                time.sleep(GOOGLE_MAPS_DELAY_SECONDS * random.uniform(0.8, 1.6))
        finally:
            browser.close()

    log(f"Xong. success={summary['success']} partial={summary['partial']} "
        f"error={summary['error']} blocked={summary['blocked']} -> {REVIEWS_FILE}")
    log(f"Bronze: {bronze_file}")


if __name__ == "__main__":
    main()