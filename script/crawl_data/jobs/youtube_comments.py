from __future__ import annotations

import time
import signal
from pathlib import Path

import pandas as pd
from ytscrape import YouTube

from ..config import (
    YOUTUBE_COMMENTS_CRAWL_LOG_FILE,
    YOUTUBE_COMMENTS_FILE,
    YOUTUBE_VIDEOS_FILE,
    MAX_COMMENTS_PER_VIDEO,
    ensure_data_directories,
    env_bool,
    env_int,
)
from ..crawlers.youtube.comments import crawl_video
from ..utils.ingestion import BronzeWriter, CheckpointStore, new_run_id
from ..metrics.ingestion import RunMetrics
from ..utils.region_priority import filter_places
from ..alerts.discord import crawl_progress
from ..utils.status import SUCCESS, classify_error, is_success_status


COMMENT_COLUMNS = [
    "place_id", "place_name", "province_id", "province_name", "video_id",
    "video_title", "comment_id", "author", "text", "likes", "is_reply",
    "comment_created_at", "crawled_at_utc",
]
LOG_COLUMNS = [
    "place_id", "place_name", "province_id", "province_name", "video_id",
    "video_title", "status", "comment_count", "error_message", "crawled_at",
]


def _append(rows: list[dict[str, object]], target: Path, columns: list[str]) -> None:
    if rows:
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows, columns=columns).to_csv(
            target, mode="a", header=not target.exists(), index=False, encoding="utf-8-sig"
        )


def _successful_videos(log_file: Path) -> set[str]:
    if not log_file.exists():
        return set()
    log = pd.read_csv(log_file, dtype=str, encoding="utf-8-sig")
    if "video_id" not in log or "status" not in log:
        return set()
    return set(log.loc[log["status"].map(is_success_status), "video_id"].dropna())


def _existing_comment_keys(comment_file: Path) -> set[tuple[str, str, str]]:
    if not comment_file.exists():
        return set()
    comments = pd.read_csv(comment_file, dtype=str, encoding="utf-8-sig").fillna("")
    required = {"video_id", "author", "text"}
    if not required.issubset(comments.columns):
        return set()
    return set(zip(comments["video_id"], comments["author"], comments["text"]))


def _comment_key(record: dict[str, object]) -> tuple[str, str, str]:
    """Return dedup key: prefer comment_id, fall back to (video_id, author, text)."""
    comment_id = str(record.get("comment_id") or "")
    if comment_id:
        return (str(record["video_id"]), "__id__", comment_id)
    return (str(record["video_id"]), str(record["author"]), str(record["text"]))


def run() -> None:
    ensure_data_directories()
    run_id = new_run_id("youtube")
    bronze_comments = BronzeWriter("youtube/comments", "youtube", run_id=run_id, crawler_version="youtube-comment-1")
    bronze_log = BronzeWriter("youtube/comments_crawl_log", "youtube", run_id=run_id, crawler_version="youtube-comment-1")
    bronze_comment_records: list[dict[str, object]] = []
    bronze_log_records: list[dict[str, object]] = []
    metrics = RunMetrics("youtube_comments", run_id)
    checkpoint = CheckpointStore("youtube/comments_crawl_log")
    videos = filter_places(pd.read_csv(YOUTUBE_VIDEOS_FILE, dtype=str, encoding="utf-8-sig").fillna(""))
    successful = _successful_videos(YOUTUBE_COMMENTS_CRAWL_LOG_FILE)
    existing_keys = _existing_comment_keys(YOUTUBE_COMMENTS_FILE)
    max_comments = env_int("YOUTUBE_COMMENTS_PER_VIDEO", MAX_COMMENTS_PER_VIDEO)
    delay_seconds = env_int("YOUTUBE_DELAY_SECONDS", 1)
    refresh_success = env_bool("TLCN_REFRESH_SUCCESS", False)
    if not refresh_success:
        videos = videos[~videos["video_id"].astype(str).isin(successful) & ~videos["video_id"].astype(str).map(checkpoint.is_success)]
    limit = env_int("YOUTUBE_COMMENT_VIDEO_LIMIT", 0)
    if limit > 0:
        videos = videos.head(limit)
    remaining = len(videos)

    def stop_handler(signum: int, frame: object) -> None:
        bronze_comments.write(bronze_comment_records)
        bronze_log.write(bronze_log_records)
        report = metrics.write()
        crawl_progress("youtube_comments", report, remaining, stopped=True)
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, stop_handler)

    with YouTube(language="vi", region="VN") as client:
        for _, row in videos.iterrows():
            video = row.to_dict()
            video_id = str(video.get("video_id", ""))
            if not video_id:
                metrics.mark("skipped")
                continue
            if not refresh_success and (video_id in successful or checkpoint.is_success(video_id)):
                metrics.mark("skipped")
                continue
            try:
                records = crawl_video(client, video, max_comments)
                for record in records:
                    record["crawled_at_utc"] = record.pop("crawled_at", "")
                new_records = []
                for record in records:
                    key = _comment_key(record)
                    if key not in existing_keys:
                        existing_keys.add(key)
                        new_records.append(record)
                _append(new_records, YOUTUBE_COMMENTS_FILE, COMMENT_COLUMNS)
                bronze_comment_records.extend(new_records)
                log_row = {**video, "status": SUCCESS, "comment_count": len(new_records),
                           "error_message": "", "crawled_at": pd.Timestamp.utcnow().isoformat()}
                _append([log_row], YOUTUBE_COMMENTS_CRAWL_LOG_FILE, LOG_COLUMNS)
                bronze_log_records.append(log_row)
                checkpoint.mark(video_id, "SUCCESS")
                metrics.mark("success")
            except Exception as error:
                log_row = {**video, "status": classify_error(error), "comment_count": 0,
                           "error_message": str(error), "crawled_at": pd.Timestamp.utcnow().isoformat()}
                _append([log_row], YOUTUBE_COMMENTS_CRAWL_LOG_FILE, LOG_COLUMNS)
                bronze_log_records.append(log_row)
                checkpoint.mark(video_id, "FAILED", error_message=str(error))
                metrics.mark("failed")
            remaining -= 1
            report = metrics.write()
            crawl_progress("youtube_comments", report, remaining)
            time.sleep(delay_seconds)
            bronze_comments.write(bronze_comment_records)
            bronze_log.write(bronze_log_records)
    report = metrics.write()
    if report["failed"]:
        raise RuntimeError(f"YouTube comments had {report['failed']} failed videos")


if __name__ == "__main__":
    run()