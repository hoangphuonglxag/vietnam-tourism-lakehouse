from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ytscrape import CommentSort


def crawl_video(client: Any, video: dict[str, str], max_comments: int) -> list[dict[str, object]]:
    video_id = str(video["video_id"])
    records: list[dict[str, object]] = []
    comments = client.comments(
        video["url"],
        include_replies=True,
        sort=CommentSort.TOP,
        max_results=max_comments,
    )
    for comment in comments:
        records.append(
            {
                "place_id": str(video.get("place_id", "")),
                "place_name": str(video.get("place_name", "")),
                "province_id": str(video.get("province_id", "")),
                "province_name": str(video.get("province_name", "")),
                "video_id": video_id,
                "video_title": str(video.get("title", "")),
                "author": comment.author,
                "text": comment.text,
                "likes": comment.like_count,
                "is_reply": comment.is_reply,
                "crawled_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
    return records