
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Iterable

from ytscrape import SearchFilter


def normalize_text(value: object, *, strip_accents: bool = False) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()

    if strip_accents:
        text = "".join(
            char
            for char in unicodedata.normalize("NFD", text)
            if unicodedata.category(char) != "Mn"
        )

    return text


def _values(place: dict[str, str], field: str) -> list[str]:
    return [
        item.strip()
        for item in str(place.get(field, "")).split("|")
        if item.strip()
    ]


def generate_queries(place: dict[str, str]) -> list[str]:
    name = str(place.get("place_name", "")).strip()
    province = str(place.get("province_name", "")).strip()

    identities = [name, *_values(place, "aliases")]
    contexts = [province, *_values(place, "query_context")]
    category_terms = _values(place, "category_terms")

    intents = (
        "du lịch",
        "review du lịch",
        "kinh nghiệm du lịch",
        "khám phá",
        "trải nghiệm",
        "tham quan",
    )

    queries: list[str] = []

    # Ưu tiên các query có từ khóa ý định du lịch (Tourism Intent) để tránh dính MV ca nhạc
    for intent in intents:
        query = f'"{name}" "{province}" {intent}'.strip()
        if query not in queries:
            queries.append(query)

    for intent in intents[:3]:
        for term in category_terms[:2]:
            query = f'"{name}" "{province}" {intent} "{term}"'.strip()
            if query not in queries:
                queries.append(query)

    for term in category_terms[:3]:
        query = f'"{name}" "{province}" "{term}"'.strip()
        if query not in queries:
            queries.append(query)

    # Chỉ bổ sung identity + context khi có kèm từ khóa ý định du lịch (Tourism Intent)
    for identity in identities:
        for context in contexts:
            query = f'{identity} {context} du lịch'.strip()
            if query and query not in queries:
                queries.append(query)

    return queries


def resolve_video(
    video: dict[str, object],
    place: dict[str, str],
) -> dict[str, object]:
    title = normalize_text(video.get("title", ""))
    description = normalize_text(video.get("description", ""))
    searchable = f"{title} {description}"

    canonical = normalize_text(place.get("place_name", ""))
    aliases = [
        normalize_text(value)
        for value in _values(place, "aliases")
    ]
    names = [name for name in [canonical, *aliases] if name]

    name_score = max(
        (
            1.0
            if name in title
            else SequenceMatcher(None, name, title).ratio()
            for name in names
        ),
        default=0.0,
    )

    location_terms = [
        normalize_text(place.get("province_name", "")),
        *[
            normalize_text(value)
            for value in _values(place, "query_context")
        ],
    ]
    location_score = min(
        1.0,
        sum(
            term in searchable
            for term in location_terms
            if term
        )
        / max(1, len(location_terms)),
    )

    context_terms = [
        normalize_text(value)
        for value in _values(place, "context_keywords")
    ]
    context_score = min(
        1.0,
        sum(
            term in searchable
            for term in context_terms
            if term
        )
        / max(1, len(context_terms)),
    )

    category_terms = [
        normalize_text(value)
        for value in _values(place, "category_terms")
    ]
    category_score = min(
        1.0,
        sum(
            term in searchable
            for term in category_terms
            if term
        )
        / max(1, len(category_terms)),
    )

    negative_terms = [
        normalize_text(value)
        for value in _values(place, "negative_keywords")
    ]
    global_negative_phrases = (
        "official mv", "music video", "official video", "phim ca nhạc", "bài hát", "ca sĩ",
        "liên khúc", "tân cổ", "bolero", "nhạc sống", "nhạc trẻ", "nhạc trữ tình",
        "hài kịch", "gameshow", "game show", "phim ngắn", "tập full", "official trailer",
        "teaser trailer", "parody", "dance practice", "remix tik tok", "nhac che",
        "nhạc chế", "rap việt", "châu khải phong", "karaoke", "soundtrack", "vevo",
        "cocomelon", "nursery rhyme", "nuclear bunker", "mrbeast", "stokes twins",
    )
    global_negative_words = {
        "karaoke", "remix", "nhạc", "nhac", "lyric", "lyrics", "audio", "mp3",
        "beat", "cover", "mv", "mashup", "acoustic", "liveshow", "ost", "soundtrack",
        "album", "single", "casi", "edm", "dj", "parody", "dance", "vpop", "kpop",
        "hài", "hai", "game", "gaming", "shorts", "tiktok", "reaction", "vevo",
    }

    words = set(searchable.split())
    negative_match = (
        any(term and term in searchable for term in negative_terms)
        or any(phrase in searchable for phrase in global_negative_phrases)
        or bool(global_negative_words & words)
    )

    video_category = normalize_text(video.get("category", ""))
    if video_category in ("music", "gaming", "autos & vehicles", "comedy", "sports", "pets & animals", "film & animation"):
        negative_match = True
    elif video_category in ("entertainment",):
        if negative_match or any(w in words for w in {"mv", "song", "ca", "hát", "bunker", "challenge"}):
            negative_match = True

    score = (
        0.50 * name_score
        + 0.20 * location_score
        + 0.15 * category_score
        + 0.15 * context_score
    )

    # Penalize partial name matches without category/context confirmation.
    if name_score < 1.0 and category_score == 0 and context_score == 0:
        score -= 0.20

    if negative_match:
        score -= 0.45

    score = max(0.0, min(1.0, score))

    status = (
        "accepted"
        if score >= 0.62 and not negative_match
        else "uncertain"
        if score >= 0.40
        else "rejected"
    )

    reason = (
        "negative_keyword"
        if negative_match
        else (
            f"name={name_score:.3f};"
            f"location={location_score:.3f};"
            f"category={category_score:.3f};"
            f"context={context_score:.3f}"
        )
    )

    return {
        "resolution_score": round(score, 4),
        "resolution_status": status,
        "resolution_reason": reason,
    }


def resolve_candidates(
    candidates: Iterable[dict[str, object]],
    place: dict[str, str],
) -> list[dict[str, object]]:
    return [
        {**candidate, **resolve_video(candidate, place)}
        for candidate in candidates
    ]


FORBIDDEN_CRAWL_CATEGORIES = {
    "music", "gaming", "autos & vehicles", "comedy",
    "sports", "pets & animals", "film & animation"
}

FORBIDDEN_CRAWL_TITLE_PATTERNS = re.compile(
    r'(official mv|music video|\[official video\]|official video|vevo|soundtrack|karaoke|remix|parody|'
    r'nhạc chế|\blyric\b|\blyrics\b|vietsub|búp bê|thiếu nhi|chữ cái|đồ chơi|cocomelon|'
    r'nursery rhyme|bunker|nuclear|doomsday|mrbeast|stokes twins|vanh leg|vlad|diana|'
    r'shaun the sheep|see you again|selena gomez|ed sheeran|sơn tùng|hoà minzy|hòa minzy|'
    r'bắc bling|bống bống bang bang|lạc trôi|\bjack\b|hà anh tuấn|charlie puth|'
    r'water balloons|experiment car|mini house)',
    re.IGNORECASE
)

FORBIDDEN_CRAWL_CHANNELS = re.compile(
    r'(mrbeast|stokes twins|cocomelon|surprisefuntv|vlad|diana|ben azelart|vevo|'
    r'vanh leg|kênh bé yêu|shaun the sheep|dreamy|music|records|audio|record|noodle & pals)',
    re.IGNORECASE
)


def crawl_place(
    client: Any,
    place: dict[str, str],
    max_videos: int,
) -> list[dict[str, object]]:
    place_id = str(place["place_id"])
    place_name = str(place["place_name"])
    province_id = str(place.get("province_id", ""))
    province_name = str(place.get("province_name", ""))
    province_name_clean = province_name.lower().strip()

    records: list[dict[str, object]] = []
    seen: set[str] = set()

    for query in generate_queries(place):
        results = client.search(
            query,
            filter=SearchFilter.VIDEOS,
            max_results=max_videos,
        )

        for result in results:
            video = client.video(result.url)
            video_id = str(video.video_id)

            if video_id in seen:
                continue

            # Hard Gate 1: Loại bỏ tuyệt đối các Category âm nhạc, game, xe cộ
            cat = str(getattr(video, "category", "") or "").lower()
            if cat in FORBIDDEN_CRAWL_CATEGORIES:
                continue

            title = str(getattr(video, "title", "") or "")
            # Hard Gate 2: Loại bỏ pattern MV âm nhạc / viral stunt quốc tế
            if FORBIDDEN_CRAWL_TITLE_PATTERNS.search(title):
                continue

            channel = str(getattr(video, "channel", "") or "")
            # Hard Gate 3: Loại bỏ các kênh spam view / nhạc / trẻ em
            if FORBIDDEN_CRAWL_CHANNELS.search(channel):
                continue

            # Hard Gate 4: Kiểm tra ngữ cảnh địa lý cho các địa danh tên tiếng Anh / ngắn
            desc = str(getattr(video, "description", "") or "").lower()
            text_corpus = f"{title.lower()} {desc}"
            if province_name_clean and len(place_name.split()) <= 2 and not any(ch.isalpha() for ch in place_name if ord(ch) > 127):
                if province_name_clean not in text_corpus:
                    continue

            seen.add(video_id)

            records.append({
                "place_id": place_id,
                "place_name": place_name,
                "province_id": province_id,
                "province_name": province_name,
                "query": query,
                "video_id": video_id,
                "title": video.title,
                "description": getattr(video, "description", ""),
                "channel_id": video.channel_id,
                "channel_name": video.channel,
                "views": video.views,
                "duration_seconds": video.length_seconds,
                "published_at": video.published,
                "category": video.category,
                "thumbnail": video.thumbnail,
                "url": video.url,
                "crawled_at": datetime.now(timezone.utc).isoformat(),
            })

            if len(records) >= max_videos:
                break

        # Early Stopping: Nếu query ý định đã tìm đủ >= 3 video chất lượng thì dừng luôn, không vét query lỏng
        if len(records) >= 3:
            break

    return records