from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable


def normalize_text(value: object, *, strip_accents: bool = False) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    if strip_accents:
        text = "".join(
            char for char in unicodedata.normalize("NFD", text)
            if unicodedata.category(char) != "Mn"
        )
    return text


def _values(place: dict[str, str], field: str) -> list[str]:
    return [item.strip() for item in str(place.get(field, "")).split("|") if item.strip()]


def generate_queries(place: dict[str, str]) -> list[str]:
    name = str(place.get("place_name", "")).strip()
    province = str(place.get("province_name", "")).strip()
    identities = [name, *_values(place, "aliases")]
    contexts = [province, *_values(place, "query_context")]
    category_terms = _values(place, "category_terms")
    intents = ("review", "khám phá", "du lịch", "tham quan", "trải nghiệm")
    queries: list[str] = []
    for identity in identities:
        for context in contexts:
            query = f'"{identity}" "{context}"'.strip()
            if query and query not in queries:
                queries.append(query)
    for term in category_terms[:3]:
        query = f'"{name}" "{province}" "{term}"'.strip()
        if query not in queries:
            queries.append(query)
    for intent in intents:
        query = f'"{name}" "{province}" {intent}'.strip()
        if query not in queries:
            queries.append(query)
    for intent in intents[:3]:
        for term in category_terms[:2]:
            query = f'"{name}" "{province}" {intent} "{term}"'.strip()
            if query not in queries:
                queries.append(query)
    return queries


def resolve_video(video: dict[str, object], place: dict[str, str]) -> dict[str, object]:
    title = normalize_text(video.get("title", ""))
    description = normalize_text(video.get("description", ""))
    searchable = f"{title} {description}"
    canonical = normalize_text(place.get("place_name", ""))
    aliases = [normalize_text(value) for value in _values(place, "aliases")]
    names = [name for name in [canonical, *aliases] if name]
    name_score = max(
        (1.0 if name in title else SequenceMatcher(None, name, title).ratio() for name in names),
        default=0.0,
    )
    location_terms = [normalize_text(place.get("province_name", "")), *_values(place, "query_context")]
    location_score = min(1.0, sum(term in searchable for term in map(normalize_text, location_terms) if term) / max(1, len(location_terms)))
    context_terms = [normalize_text(value) for value in _values(place, "context_keywords")]
    context_score = min(1.0, sum(term in searchable for term in context_terms if term) / max(1, len(context_terms)))
    category_terms = [normalize_text(value) for value in _values(place, "category_terms")]
    category_score = min(1.0, sum(term in searchable for term in category_terms if term) / max(1, len(category_terms)))
    negative_terms = [normalize_text(value) for value in _values(place, "negative_keywords")]
    negative_match = any(term and term in searchable for term in negative_terms)
    score = 0.50 * name_score + 0.20 * location_score + 0.15 * category_score + 0.15 * context_score
    if negative_match:
        score -= 0.45
    score = max(0.0, min(1.0, score))
    status = "accepted" if score >= 0.62 and not negative_match else "uncertain" if score >= 0.40 else "rejected"
    reason = "negative_keyword" if negative_match else (
        f"name={name_score:.3f};location={location_score:.3f};"
        f"category={category_score:.3f};context={context_score:.3f}"
    )
    return {"resolution_score": round(score, 4), "resolution_status": status, "resolution_reason": reason}


def resolve_candidates(candidates: Iterable[dict[str, object]], place: dict[str, str]) -> list[dict[str, object]]:
    return [{**candidate, **resolve_video(candidate, place)} for candidate in candidates]