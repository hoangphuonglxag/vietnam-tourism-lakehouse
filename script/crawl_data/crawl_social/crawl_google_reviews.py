from __future__ import annotations

import difflib
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from ..config import MAX_REVIEWS_PER_PLACE


@dataclass(frozen=True)
class Place:
    place_id: str
    place_name: str
    province_name: str
    latitude: str = ""
    longitude: str = ""


@dataclass(frozen=True)
class Review:
    review_id: str
    place_id: str
    rating: int | None
    review_text: str | None
    review_date: str | None
    likes_count: int | None
    source: str
    crawled_at_utc: str


CARD = "[data-review-id]"
TAB_RE = re.compile(r"Bài đánh giá|Đánh giá|Reviews?", re.IGNORECASE)
SORT_BTN_RE = re.compile(
    r"Sắp xếp|Sort|Phù hợp nhất|Most relevant|Mới nhất|Newest|"
    r"Cao nhất|Highest|Thấp nhất|Lowest",
    re.IGNORECASE,
)
NEWEST_RE = re.compile(r"Mới nhất|Newest", re.IGNORECASE)
BLOCKED_RE = re.compile(
    r"unusual traffic|automated quer|our systems have detected|"
    r"xác minh bạn không phải là robot|captcha|sorry/index",
    re.IGNORECASE,
)

COUNT_JS = """() => new Set([...document.querySelectorAll('[data-review-id]')]
  .map(e => e.getAttribute('data-review-id')).filter(Boolean)).size"""

FIRST_ID_JS = """() => document.querySelector('[data-review-id]')?.getAttribute('data-review-id') || ''"""

TAB_SELECTED_JS = r"""() => [...document.querySelectorAll('[role="tab"]')].some(t =>
  t.getAttribute('aria-selected') === 'true' &&
  /Bài đánh giá|Đánh giá|Reviews?/i.test((t.getAttribute('aria-label') || '') + ' ' + t.innerText))"""

EXPAND_JS = r"""() => {
  const buttons = document.querySelectorAll(
    '[data-review-id] button.w8nwRe, ' +
    '[data-review-id] button[aria-label="Xem thêm"], ' +
    '[data-review-id] button[aria-label="See more"]'
  );
  buttons.forEach(button => { try { button.click(); } catch (e) {} });
  return buttons.length;
}"""

FIND_PANEL_RECT_JS = r"""() => {
  const card = document.querySelector('[data-review-id]');
  if (!card) return {ok: false, why: 'no-review-card'};
  let el = card.parentElement;
  while (el) {
    const style = getComputedStyle(el);
    if (el.scrollHeight > el.clientHeight + 20 && /(auto|scroll)/.test(style.overflowY)) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) return {
        ok: true, why: 'review-card-ancestor',
        rect: {x: r.x, y: r.y, width: r.width, height: r.height},
        scrollTop: el.scrollTop, scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight, overflowY: style.overflowY,
        tag: el.tagName, role: el.getAttribute('role'),
        cls: (el.className || '').toString().slice(0, 120)
      };
    }
    el = el.parentElement;
  }
  return {ok: false, why: 'no-scrollable-review-ancestor'};
}"""

PARSE_JS = r"""() => {
  const seen = new Map();
  document.querySelectorAll('[data-review-id]').forEach(card => {
    const id = card.getAttribute('data-review-id');
    if (id && !seen.has(id)) seen.set(id, card);
  });
  return [...seen.entries()].map(([id, card]) => {
    const q = selector => card.querySelector(selector);
    const star = (q('span.kvMYJc') || q('[role="img"][aria-label]'))?.getAttribute('aria-label') || '';
    const textEl = [...card.querySelectorAll('span.wiI7pd')].find(el => !el.closest('.CDe7pd'));
    return {
      review_id: id,
      rating: (star.match(/\d+/) || [null])[0],
      review_text: (textEl?.innerText || '').trim(),
      review_date: (q('span.rsqaWe')?.innerText || '').trim(),
      likes_count: (q('span.pkWtMe')?.innerText || '0').trim()
    };
  });
}"""


class GoogleMapsReviewsCrawler:
    """Google Maps review crawler using real mouse-wheel events for lazy loading."""

    def __init__(self, context: Any, timeout_ms: int = 45_000) -> None:
        self.context = context
        self.page = context.new_page()
        self.page.set_default_timeout(timeout_ms)
        self.last_status = "NOT_STARTED"
        self.last_total_reviews: int | None = None
        self.last_found_name = ""
        self.last_url = ""

    def close(self) -> None:
        try:
            self.page.close()
        except Exception:
            pass

    def crawl_place(self, place: Place, max_count: int | None = None) -> list[Review]:
        if max_count is None:
            max_count = MAX_REVIEWS_PER_PLACE
        self.last_status = "FAILED"
        self.last_total_reviews = None
        self.last_found_name = ""
        self.last_url = ""

        self._open_place(place)
        if not self._open_reviews_tab():
            raise RuntimeError("Không mở được tab Bài đánh giá hoặc review không tải.")

        # Giữ nguyên luồng crawl_review: cố gắng chọn Mới nhất nhưng vẫn crawl
        # nếu Google thay đổi UI khiến không thể xác nhận được menu sắp xếp.
        if not self._sort_by_newest():
            print(f"[WARN] Không xác nhận được sort Mới nhất: {place.place_name}", flush=True)

        self.last_total_reviews = self._get_total_review_count()
        rows = self._scroll_and_collect(max_count)
        if not rows:
            self.last_status = "EMPTY"
            return []

        if max_count and max_count > 0 and len(rows) >= max_count:
            self.last_status = "SUCCESS"
        elif self.last_total_reviews is not None and len(rows) >= self.last_total_reviews:
            self.last_status = "SUCCESS"
        else:
            self.last_status = "PARTIAL"
        return self._extract(place, max_count)

    def _open_place(self, place: Place) -> None:
        query = f"{place.place_name} {place.province_name}".strip()
        url = f"https://www.google.com/maps/search/{quote(query)}?hl=vi"
        self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        self._handle_consent()
        self._check_blocked()
        self.page.wait_for_timeout(2_500)

        if "/maps/place/" not in self.page.url:
            try:
                self.page.wait_for_function(
                    "() => location.href.includes('/maps/place/') || "
                    "document.querySelector('a.hfpxzc') !== null",
                    timeout=15_000,
                )
            except Exception:
                pass

        if "/maps/place/" not in self.page.url:
            results = self.page.locator('a.hfpxzc, div[role="feed"] a[href*="/maps/place/"]')
            clicked = False
            try:
                count = min(results.count(), 10)
            except Exception:
                count = 0
            for index in range(count):
                result = results.nth(index)
                try:
                    result_name = result.inner_text(timeout=1_000).strip()
                except Exception:
                    result_name = result.get_attribute("aria-label") or ""
                if self._name_matches(place.place_name, result_name):
                    result.click(timeout=5_000)
                    clicked = True
                    break
            if not clicked and count:
                results.first.click(timeout=5_000)
            try:
                self.page.wait_for_url(re.compile(r"/maps/place/"), timeout=15_000)
            except Exception:
                pass
            self.page.wait_for_timeout(2_500)

        self._handle_consent()
        self._check_blocked()
        if "/maps/place/" not in self.page.url:
            raise RuntimeError(f"Không mở được trang place. url={self.page.url}")

        try:
            self.page.locator("h1.DUwDvf").first.wait_for(state="visible", timeout=15_000)
            found_name = self.page.locator("h1.DUwDvf").first.inner_text(timeout=5_000).strip()
        except Exception:
            found_name = ""
        if found_name and not self._name_matches(place.place_name, found_name):
            raise RuntimeError(
                f"Google Maps mở sai place. cần={place.place_name!r}, found={found_name!r}"
            )
        self.last_found_name = found_name
        self.last_url = self.page.url

    def _open_reviews_tab(self) -> bool:
        for reload_no in range(2):
            if reload_no:
                self.page.reload(wait_until="domcontentloaded", timeout=30_000)
                self._handle_consent()
                self._check_blocked()
                self.page.wait_for_timeout(3_000)
            for attempt in range(1, 4):
                try:
                    tab = self.page.get_by_role("tab", name=TAB_RE).first
                    tab.wait_for(state="visible", timeout=5_000)
                    tab.scroll_into_view_if_needed()
                    tab.click(timeout=5_000)
                    try:
                        self.page.wait_for_function(TAB_SELECTED_JS, timeout=5_000)
                    except Exception:
                        pass
                    self.page.wait_for_selector(CARD, timeout=10_000)
                    return True
                except Exception:
                    self._check_blocked()
                    self.page.wait_for_timeout(1_000 * attempt)
        return False

    def _sort_by_newest(self) -> bool:
        button = self.page.locator("button.HQzyZ").first
        try:
            button.wait_for(state="visible", timeout=10_000)
        except Exception:
            button = self.page.get_by_role("button", name=SORT_BTN_RE).first
            try:
                button.wait_for(state="visible", timeout=8_000)
            except Exception:
                return False

        current = (button.get_attribute("aria-label") or button.inner_text() or "").strip()
        if NEWEST_RE.search(current) or "moi nhat" in self._norm(current):
            return True

        first_before = self.page.evaluate(FIRST_ID_JS)
        try:
            button.click(timeout=5_000)
        except Exception:
            return False
        newest_pattern = re.compile(r"^Mới nhất$|^Mới nhất$|^Newest$", re.IGNORECASE)
        try:
            menu = self.page.locator('[role="menu"]').last
            newest = menu.get_by_text(newest_pattern).first
            if not newest.count():
                newest = self.page.get_by_text(newest_pattern).last
            newest.click(timeout=5_000)
        except Exception:
            try:
                self.page.get_by_text(newest_pattern).last.click(timeout=5_000, force=True)
            except Exception:
                return False
        try:
            self.page.wait_for_function(
                "old => { const card = document.querySelector('[data-review-id]'); "
                "return !!card && card.getAttribute('data-review-id') !== old; }",
                arg=first_before,
                timeout=10_000,
            )
        except Exception:
            pass
        try:
            self.page.wait_for_selector(CARD, timeout=10_000)
        except Exception:
            return False
        return True

    def _get_total_review_count(self) -> int | None:
        candidates = ["div.F7nice", "span.F7nice", 'button[jsaction*="reviewChart"]']
        text = ""
        for selector in candidates:
            try:
                text = self.page.locator(selector).first.inner_text(timeout=2_000)
                if text:
                    break
            except Exception:
                continue
        if not text:
            try:
                text = self.page.locator("h1.DUwDvf").first.locator("xpath=../..").inner_text(timeout=2_000)
            except Exception:
                return None
        match = re.search(r"([\d.,]+)\s*(?:bài đánh giá|đánh giá|reviews?)", text, re.IGNORECASE)
        if not match:
            return None
        try:
            return int(match.group(1).replace(".", "").replace(",", ""))
        except ValueError:
            return None

    def _locate_panel_center(self) -> tuple[float, float] | None:
        try:
            info = self.page.evaluate(FIND_PANEL_RECT_JS)
        except Exception:
            return None
        if not info or not info.get("ok"):
            return None
        rect = info["rect"]
        x = rect["x"] + rect["width"] / 2
        y = rect["y"] + max(rect["height"] * 0.4, 100)
        # Clamp point inside the visible panel to avoid browser chrome/footer.
        y = min(y, rect["y"] + rect["height"] - 20)
        return x, y

    def _get_scroll_debug(self) -> dict[str, Any] | None:
        try:
            info = self.page.evaluate(FIND_PANEL_RECT_JS)
        except Exception:
            return None
        if not info or not info.get("ok"):
            return None
        return {key: info.get(key) for key in ("scrollTop", "scrollHeight", "clientHeight", "tag", "role", "cls")}

    def _scroll_and_collect(self, max_count: int) -> list[dict[str, Any]]:
        def count_reviews() -> int:
            try:
                return int(self.page.evaluate(COUNT_JS))
            except Exception:
                return 0

        last = count_reviews()
        if max_count and max_count > 0 and last >= max_count:
            self.page.evaluate(EXPAND_JS)
            self.page.wait_for_timeout(500)
            return self.page.evaluate(PARSE_JS)[:max_count]

        stagnant = 0
        max_stagnant = 10
        iteration = 0
        point = self._locate_panel_center()
        if point:
            self.page.mouse.move(*point)

        while not (max_count and max_count > 0 and last >= max_count):
            iteration += 1
            point = self._locate_panel_center()
            before_scroll = self._get_scroll_debug()
            before_count = count_reviews()
            if point:
                self.page.mouse.move(*point)
                # Critical: use real wheel events; do not mutate scrollTop in JS.
                self.page.mouse.wheel(0, 500)
            else:
                # A real keyboard event is a fallback when the scroll panel is not found.
                self.page.keyboard.press("End")
            self.page.wait_for_timeout(1_000)
            after_scroll = self._get_scroll_debug()
            now = count_reviews()
            if now > last:
                last = now
                stagnant = 0
            else:
                stagnant += 1
            if before_scroll and after_scroll:
                if after_scroll.get("scrollTop") == before_scroll.get("scrollTop") and now <= before_count:
                    # Give the UI one additional wheel attempt before counting this as stagnant.
                    point = self._locate_panel_center()
                    if point:
                        self.page.mouse.move(*point)
                        self.page.mouse.wheel(0, 900)
                        self.page.wait_for_timeout(800)
                        retry_count = count_reviews()
                        if retry_count > last:
                            last = retry_count
                            stagnant = 0
            if stagnant >= max_stagnant:
                break
            self._check_blocked()

        self.page.evaluate(EXPAND_JS)
        self.page.wait_for_timeout(500)
        rows = self.page.evaluate(PARSE_JS)
        return rows[:max_count] if max_count and max_count > 0 else rows

    def _extract(self, place: Place, max_count: int | None = None) -> list[Review]:
        crawled_at = datetime.now(timezone.utc).isoformat()
        rows = self.page.evaluate(PARSE_JS)
        reviews: list[Review] = []
        seen_ids: set[str] = set()
        for row in rows:
            text = self._clean(row.get("review_text"))
            review_id = self._clean(row.get("review_id"))
            if not review_id:
                review_id = hashlib.sha1(f"{place.place_id}|{text or ''}".encode("utf-8")).hexdigest()
            if review_id in seen_ids:
                continue
            seen_ids.add(review_id)
            reviews.append(
                Review(
                    review_id=review_id,
                    place_id=place.place_id,
                    rating=self._int(row.get("rating")),
                    review_text=text,
                    review_date=self._clean(row.get("review_date")),
                    likes_count=self._int(row.get("likes_count")),
                    source="google_maps",
                    crawled_at_utc=crawled_at,
                )
            )
        return reviews[:max_count] if max_count and max_count > 0 else reviews

    def _handle_consent(self) -> None:
        patterns = [
            re.compile(r"Accept all|I agree|Chấp nhận tất cả|Đồng ý", re.IGNORECASE),
        ]
        for pattern in patterns:
            try:
                button = self.page.get_by_role("button", name=pattern).first
                button.wait_for(state="visible", timeout=500)
                button.click(timeout=2_000)
                self.page.wait_for_timeout(500)
                return
            except Exception:
                pass

    def _check_blocked(self) -> None:
        url = self.page.url or ""
        try:
            body = self.page.locator("body").inner_text(timeout=1_000)[:8_000]
        except Exception:
            body = ""
        if "sorry/index" in url or BLOCKED_RE.search(body):
            raise RuntimeError("Google Maps có dấu hiệu CAPTCHA/chặn truy cập; dừng place hiện tại.")

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        value = re.sub(r"\s+", " ", str(value)).strip()
        return value or None

    @staticmethod
    def _int(value: Any) -> int | None:
        match = re.search(r"\d[\d.,]*", str(value or ""))
        return int(re.sub(r"\D", "", match.group(0))) if match else None

    @staticmethod
    def _norm(value: str) -> str:
        value = unicodedata.normalize("NFD", value.lower().replace("đ", "d"))
        value = "".join(char for char in value if unicodedata.category(char) != "Mn")
        return " ".join(re.sub(r"[^a-z0-9 ]+", " ", value).split())

    @classmethod
    def _name_matches(cls, wanted: str, found: str) -> bool:
        wanted_norm = cls._norm(wanted)
        found_norm = cls._norm(found)
        if not wanted_norm or not found_norm:
            return True
        return (
            wanted_norm in found_norm
            or found_norm in wanted_norm
            or difflib.SequenceMatcher(None, wanted_norm, found_norm).ratio() >= 0.6
        )


__all__ = ["GoogleMapsReviewsCrawler", "Place", "Review"]
