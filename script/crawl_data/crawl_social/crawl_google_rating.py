from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote


def _search_url(place: dict[str, str]) -> str:
    query = f"{place.get('place_name', '')}, {place.get('province_name', '')}, Vietnam"
    return "https://www.google.com/maps/search/?api=1&query=" + quote(query)


def _distribution(labels: list[str]) -> dict[int, int]:
    result = {rating: 0 for rating in range(1, 6)}
    pattern = re.compile(r"([1-5])\s*sao,\s*([\d.,]+)\s*bài\s+đánh\s+giá", re.IGNORECASE)
    for label in labels:
        match = pattern.search(label)
        if match:
            result[int(match.group(1))] = int(re.sub(r"\D", "", match.group(2)))
    return result


def crawl_place(page: Any, place: dict[str, str]) -> dict[str, object]:
    page.goto(_search_url(place), wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(4_000)
    rating = None
    candidates = page.locator('[role="img"][aria-label*="sao"]')
    for index in range(min(candidates.count(), 30)):
        label = candidates.nth(index).get_attribute("aria-label") or ""
        match = re.search(r"([0-5](?:[.,]\d+)?)\s*sao", label, re.IGNORECASE)
        if match and 0 <= float(match.group(1).replace(",", ".")) <= 5:
            rating = float(match.group(1).replace(",", "."))
            break
    rows = page.locator('tr[role="img"][aria-label]')
    labels = [rows.nth(index).get_attribute("aria-label") or "" for index in range(rows.count())]
    distribution = _distribution(labels)
    return {
        "google_rating": rating,
        "google_review_count": sum(distribution.values()),
        **{f"rating_{key}_count": value for key, value in distribution.items()},
        "crawled_at": datetime.now(timezone.utc).isoformat(),
    }