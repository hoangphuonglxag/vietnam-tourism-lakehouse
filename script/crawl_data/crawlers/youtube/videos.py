from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ytscrape import SearchFilter

from .resolution import generate_queries


def crawl_place(client: Any, place: dict[str, str], max_videos: int) -> list[dict[str, object]]:
    place_id = str(place["place_id"])
    place_name = str(place["place_name"])
    province_id = str(place.get("province_id", ""))
    province_name = str(place.get("province_name", ""))
    records: list[dict[str, object]] = []

    seen: set[str] = set()
    for query in generate_queries(place):
        for result in client.search(query, filter=SearchFilter.VIDEOS, max_results=max_videos):
            video = client.video(result.url)
            video_id = str(video.video_id)
            if video_id in seen:
                continue
            seen.add(video_id)
            records.append({
                "place_id": place_id, "place_name": place_name,
                "province_id": province_id, "province_name": province_name,
                "query": query, "video_id": video_id, "title": video.title,
                "description": getattr(video, "description", ""),
                "channel_id": video.channel_id, "channel_name": video.channel,
                "views": video.views, "duration_seconds": video.length_seconds,
                "published_at": video.published, "category": video.category,
                "thumbnail": video.thumbnail, "url": video.url,
                "crawled_at": datetime.now(timezone.utc).isoformat(),
            })
    return records