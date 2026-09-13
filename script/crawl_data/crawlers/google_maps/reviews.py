from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote


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


def _clean(value: str | None) -> str | None:
	if value is None:
		return None
	value = re.sub(r"\s+", " ", value).strip()
	return value or None


def _int(value: str | None) -> int | None:
	match = re.search(r"\d[\d.,]*", value or "")
	return int(re.sub(r"\D", "", match.group(0))) if match else None


class GoogleMapsReviewsCrawler:
	def __init__(self, context: Any, timeout_ms: int = 45_000) -> None:
		self.context = context
		self.page = context.new_page()
		self.page.set_default_timeout(timeout_ms)

	def close(self) -> None:
		self.context.close()

	def crawl_place(self, place: Place) -> list[Review]:
		query = f"{place.place_name}, {place.province_name}, Vietnam {place.latitude},{place.longitude}"
		self.page.goto(
			"https://www.google.com/maps/search/?api=1&query=" + quote(query),
			wait_until="domcontentloaded",
		)
		self.page.wait_for_timeout(3000)
		self._open_reviews()
		self._scroll_reviews()
		return self._extract(place)

	def _open_reviews(self) -> None:
		pattern = re.compile(r"(Bài đánh giá|Đánh giá|Reviews)", re.IGNORECASE)
		for locator in (
			self.page.get_by_role("tab", name=pattern),
			self.page.get_by_role("button", name=pattern),
			self.page.locator('button[aria-label*="Bài đánh giá"]'),
		):
			if locator.count():
				try:
					locator.first.click(timeout=5000)
					self.page.wait_for_timeout(1500)
					return
				except Exception:
					continue

	def _scroll_reviews(self) -> None:
		container = self.page.locator("div.m6QErb").last
		for _ in range(10):
			try:
				container.evaluate("element => element.scrollTop = element.scrollHeight")
				self.page.wait_for_timeout(1000)
			except Exception:
				return

	def _extract(self, place: Place) -> list[Review]:
		cards = self.page.locator('div[data-review-id], div.jftiEf')
		reviews: list[Review] = []
		for index in range(cards.count()):
			card = cards.nth(index)
			review_id = _clean(card.get_attribute("data-review-id"))
			text = self._text(card, ".wiI7pd", "span[jsan*='wiI7pd']")
			author = self._text(card, ".d4r55", ".TSUbDb") or "unknown"
			if not review_id:
				review_id = hashlib.sha1(f"{place.place_id}|{author}|{text}".encode()).hexdigest()
			rating = None
			label = card.locator('[role="img"][aria-label]').first.get_attribute("aria-label")
			match = re.search(r"([1-5])\s*(?:sao|star)", label or "", re.IGNORECASE)
			if match:
				rating = int(match.group(1))
			reviews.append(Review(
				review_id=review_id,
				place_id=place.place_id,
				rating=rating,
				review_text=text,
				review_date=self._text(card, ".rsqaWe", "span.rsqaWe"),
				likes_count=_int(self._text(card, "button[aria-label*='Like']")),
				source="Google Maps",
				crawled_at_utc=datetime.now(timezone.utc).isoformat(),
			))
		return reviews

	@staticmethod
	def _text(card: Any, *selectors: str) -> str | None:
		for selector in selectors:
			locator = card.locator(selector)
			if locator.count():
				value = _clean(locator.first.inner_text())
				if value:
					return value
		return None


__all__ = ["GoogleMapsReviewsCrawler", "Place", "Review"]