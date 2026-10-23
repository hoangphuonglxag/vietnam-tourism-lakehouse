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
        # comment_id: use source-provided ID for deduplication (proposal §6)
        comment_id = getattr(comment, "comment_id", None) or getattr(comment, "id", None)

        # comment_created_at: required if source provides it (proposal §6)
        raw_published = getattr(comment, "published", None) or getattr(comment, "published_at", None)
        comment_created_at = str(raw_published) if raw_published is not None else None

        records.append(
            {
                "place_id": str(video.get("place_id", "")),
                "place_name": str(video.get("place_name", "")),
                "province_id": str(video.get("province_id", "")),
                "province_name": str(video.get("province_name", "")),
                "video_id": video_id,
                "video_title": str(video.get("title", "")),
                "comment_id": comment_id,
                "author": comment.author,
                "text": comment.text,
                "likes": comment.like_count,
                "is_reply": comment.is_reply,
                "comment_created_at": comment_created_at,
                "crawled_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
    return records