from __future__ import annotations

import hashlib
import difflib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from ...config import MAX_REVIEWS_PER_PLACE


@dataclass(frozen=True)
class Place:
    place_id: str
    place_name: str
    province_name: str
    latitude: str
    longitude: str


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
    r"Cao nhất|Highest|Thấp nhất|Lowest", re.IGNORECASE
)
NEWEST_RE = re.compile(r"Mới nhất|Newest", re.IGNORECASE)

COUNT_JS = """
() => new Set([...document.querySelectorAll('[data-review-id]')]
  .map(e => e.getAttribute('data-review-id'))).size
"""

FIRST_ID_JS = """
() => document.querySelector('[data-review-id]')?.getAttribute('data-review-id') || ''
"""

EXPAND_JS = """
() => {
    document.querySelectorAll(
        '[data-review-id] button.w8nwRe,' +
        '[data-review-id] button[aria-label="Xem thêm"],' +
        '[data-review-id] button[aria-label="See more"]'
    ).forEach(button => {
        try {
            button.click();
        } catch (error) {}
    });
}
"""

PARSE_JS = """
() => {
  const seen = new Map();
  document.querySelectorAll('[data-review-id]').forEach(card => {
    const id = card.getAttribute('data-review-id');
    if (id && !seen.has(id)) seen.set(id, card);
  });
  return [...seen.entries()].map(([id, card]) => {
    const query = selector => card.querySelector(selector);
    const star = (query('span.kvMYJc') || query('[role="img"][aria-label]'))
      ?.getAttribute('aria-label') || '';
    const text = [...card.querySelectorAll('span.wiI7pd')]
      .find(element => !element.closest('.CDe7pd'));
    return {
      review_id: id,
      rating: (star.match(/\d+/) || [null])[0],
      review_text: (text?.innerText || '').trim(),
      review_date: (query('span.rsqaWe')?.innerText || '').trim(),
      likes_count: (query('span.pkWtMe')?.innerText || '0').trim(),
    };
  });
}
"""


class GoogleMapsReviewsCrawler:
    """Crawl the Google Maps UI flow verified by tests/crawl_review.py."""

    def __init__(self, context: Any, timeout_ms: int = 45_000) -> None:
        self.context = context
        self.page = context.new_page()
        self.page.set_default_timeout(timeout_ms)

    def close(self) -> None:
        self.context.close()

    def crawl_place(self, place: Place, max_count: int | None = None) -> list[Review]:
        if max_count is None:
            max_count = MAX_REVIEWS_PER_PLACE
        self._open_place(place)
        if not self._open_reviews_tab():
            return []
        if not self._sort_by_newest():
            raise RuntimeError("Không thể chuyển sang Mới nhất")
        self._scroll_and_collect(max_count)
        self.page.evaluate(EXPAND_JS)
        self.page.wait_for_timeout(700)
        return self._extract(place, max_count)

    def _open_place(self, place: Place) -> None:
        query = f"{place.place_name} {place.province_name}".strip()
        self.page.goto(
            f"https://www.google.com/maps/search/{quote(query)}?hl=vi",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        self.page.wait_for_timeout(3_000)

        if "/maps/place/" not in self.page.url:
            self.page.wait_for_function(
                "() => location.href.includes('/maps/place/') || "
                "document.querySelector('a.hfpxzc') !== null",
                timeout=15_000,
            )
            if "/maps/place/" not in self.page.url:
                results = self.page.locator("a.hfpxzc")
                if not results.count():
                    raise RuntimeError(f"Không có result place. url={self.page.url}")
                clicked = False
                for index in range(min(results.count(), 10)):
                    result = results.nth(index)
                    try:
                        text = result.inner_text(timeout=1_000).strip()
                    except Exception:
                        text = ""
                    if self._name_matches(place.place_name, text):
                        result.click()
                        clicked = True
                        break
                if not clicked:
                    results.first.click()
                try:
                    self.page.wait_for_url(re.compile(r"/maps/place/"), timeout=15_000)
                except Exception:
                    pass
                self.page.wait_for_timeout(3_000)

        if "/maps/place/" not in self.page.url:
            raise RuntimeError(f"Không mở được trang place. url={self.page.url}")

        try:
            self.page.locator("h1.DUwDvf").first.wait_for(state="visible", timeout=15_000)
        except Exception:
            pass
        found_name = self.page.locator("h1.DUwDvf").first.inner_text(timeout=5_000).strip()
        if not self._name_matches(place.place_name, found_name):
            raise RuntimeError(
                f"Google Maps mở sai place. cần={place.place_name!r}, found={found_name!r}"
            )

    def _open_reviews_tab(self) -> bool:
        for reload_no in range(2):
            if reload_no:
                self.page.reload(wait_until="domcontentloaded", timeout=30_000)
                self.page.wait_for_timeout(3_000)
            for attempt in range(3):
                try:
                    tab = self.page.get_by_role("tab", name=TAB_RE).first
                    tab.wait_for(state="visible", timeout=5_000)
                    tab.scroll_into_view_if_needed()
                    tab.click(timeout=5_000)
                    self.page.wait_for_selector(CARD, timeout=10_000)
                    return True
                except Exception:
                    self.page.wait_for_timeout(1_500 * (attempt + 1))
        return False

    def _sort_by_newest(self) -> bool:
        button = self.page.locator("button.HQzyZ").first
        try:
            button.wait_for(state="visible", timeout=15_000)
        except Exception:
            button = self.page.get_by_role("button", name=SORT_BTN_RE).first
            try:
                button.wait_for(state="visible", timeout=10_000)
            except Exception:
                return False

        current = (button.get_attribute("aria-label") or button.inner_text()).strip()
        if NEWEST_RE.search(current) or "moi nhat" in self._norm(current):
            return True

        first_before = self.page.evaluate(FIRST_ID_JS)
        button.click(timeout=5_000)
        newest_pattern = re.compile(
            r"^Mới nhất$|^Mới nhất$|^Newest$", re.IGNORECASE
        )
        menu = self.page.locator("[role='menu']").last
        newest = menu.get_by_text(newest_pattern).first
        if not newest.count():
            newest = self.page.get_by_text(newest_pattern).last
        try:
            newest.click(timeout=5_000)
        except Exception:
            newest.click(timeout=5_000, force=True)

        try:
            self.page.wait_for_function(
                "old => { const card = document.querySelector('[data-review-id]'); "
                "return !!card && card.getAttribute('data-review-id') !== old; }",
                arg=first_before,
                timeout=10_000,
            )
        except Exception:
            pass
        self.page.wait_for_selector(CARD, timeout=10_000)
        return True

    def _scroll_and_collect(self, max_count: int) -> int:
        last = self.page.evaluate(COUNT_JS)
        stagnant = 0
        iteration = 0
        max_stagnant = 8

        while True:
            iteration += 1
            if max_count and last >= max_count:
                break

            try:
                self.page.evaluate(
                    """
                    () => {
                      const card = document.querySelector('[data-review-id]');
                      if (!card) return { ok: false, reason: 'no-review-card' };
                      let element = card.parentElement;
                      while (element) {
                        const style = getComputedStyle(element);
                        if (
                          element.scrollHeight > element.clientHeight + 20 &&
                          /(auto|scroll)/.test(style.overflowY)
                        ) {
                          const before = element.scrollTop;
                          element.scrollTop = element.scrollHeight;
                          element.dispatchEvent(new Event('scroll', { bubbles: true }));
                          return { ok: true, before, after: element.scrollTop, height: element.scrollHeight, client: element.clientHeight };
                        }
                        element = element.parentElement;
                      }
                      return { ok: false, reason: 'scroll-container-not-found' };
                    }
                    """
                )
            except Exception:
                pass

            self.page.wait_for_timeout(int(1000 * max(0.8, min(1.5, 1.0))))
            now = self.page.evaluate(COUNT_JS)
            if now > last:
                last = now
                stagnant = 0
                continue

            try:
                card = self.page.locator(CARD).last
                box = card.bounding_box()
                if box:
                    self.page.mouse.move(
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                    )
                    self.page.mouse.wheel(0, 1_500)
            except Exception:
                pass

            self.page.wait_for_timeout(1_200)
            now = self.page.evaluate(COUNT_JS)
            if now > last:
                last = now
                stagnant = 0
                continue

            stagnant += 1
            if stagnant >= max_stagnant:
                break

        return last

    def _extract(self, place: Place, max_count: int | None = None) -> list[Review]:
        crawled_at = datetime.now(timezone.utc).isoformat()
        rows = self.page.evaluate(PARSE_JS)
        reviews: list[Review] = []
        for row in rows:
            review_id = row.get("review_id")
            text = self._clean(row.get("review_text"))
            if not review_id:
                review_id = hashlib.sha1(
                    f"{place.place_id}|{text}".encode("utf-8")
                ).hexdigest()
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
        if max_count and max_count > 0:
            return reviews[:max_count]
        return reviews

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        value = re.sub(r"\s+", " ", value).strip()
        return value or None

    @staticmethod
    def _int(value: str | None) -> int | None:
        match = re.search(r"\d[\d.,]*", value or "")
        return int(re.sub(r"\D", "", match.group(0))) if match else None

    @staticmethod
    def _norm(value: str) -> str:
        value = unicodedata.normalize("NFD", value.lower().replace("đ", "d"))
        value = "".join(
            char for char in value if unicodedata.category(char) != "Mn"
        )
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
