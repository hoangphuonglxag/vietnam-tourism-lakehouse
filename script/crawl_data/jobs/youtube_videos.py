from __future__ import annotations

import time
import signal
from pathlib import Path

import pandas as pd
from ytscrape import YouTube

from ..config import (
    PLACES_FILE,
    YOUTUBE_CRAWL_LOG_FILE,
    YOUTUBE_VIDEOS_FILE,
    ensure_data_directories,
    env_bool,
    env_int,
)
from ..crawlers.youtube.videos import crawl_place
from ..ingestion import BronzeWriter, CheckpointStore, new_run_id
from ..metrics.ingestion import RunMetrics
from ..region_priority import filter_places
from ..alerts.discord import crawl_progress


VIDEO_COLUMNS = [
    "place_id", "place_name", "province_id", "province_name", "query",
    "video_id", "title", "channel_id", "channel_name", "views",
    "duration_seconds", "published_at", "category", "thumbnail", "url",
    "crawled_at",
]

LOG_COLUMNS = [
    "place_id", "place_name", "province_id", "province_name", "query",
    "status", "video_count", "error_message", "crawled_at",
]


def _append(rows: list[dict[str, object]], target: Path, columns: list[str]) -> None:
    if not rows:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns).to_csv(
        target, mode="a", header=not target.exists(), index=False, encoding="utf-8-sig"
    )


def _successful_places(log_file: Path) -> set[str]:
    if not log_file.exists():
        return set()
    log = pd.read_csv(log_file, dtype=str, encoding="utf-8-sig")
    if "place_id" not in log or "status" not in log:
        return set()
    return set(log.loc[log["status"] == "success", "place_id"].dropna())


def _existing_video_keys(video_file: Path) -> set[tuple[str, str]]:
    if not video_file.exists():
        return set()
    videos = pd.read_csv(video_file, dtype=str, encoding="utf-8-sig")
    if not {"place_id", "video_id"}.issubset(videos.columns):
        return set()
    return set(zip(videos["place_id"].dropna(), videos["video_id"].dropna()))


def run() -> None:
    ensure_data_directories()
    run_id = new_run_id("youtube")
    bronze_videos = BronzeWriter("youtube/videos", "youtube", run_id=run_id, crawler_version="youtube-video-1")
    bronze_log = BronzeWriter("youtube/crawl_log", "youtube", run_id=run_id, crawler_version="youtube-video-1")
    checkpoint = CheckpointStore("youtube/crawl_log")
    places = pd.read_csv(PLACES_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    places = filter_places(places)
    successful = _successful_places(YOUTUBE_CRAWL_LOG_FILE)
    existing_keys = _existing_video_keys(YOUTUBE_VIDEOS_FILE)
    max_videos = env_int("YOUTUBE_MAX_VIDEOS", 5)
    delay_seconds = env_int("YOUTUBE_DELAY_SECONDS", 1)
    refresh_success = env_bool("TLCN_REFRESH_SUCCESS", False)
    metrics = RunMetrics("youtube_videos", run_id)
    if not refresh_success:
        places = places[~places["place_id"].astype(str).isin(successful) & ~places["place_id"].astype(str).map(checkpoint.is_success)]
    limit = env_int("YOUTUBE_MAX_PLACES", 0)
    if limit > 0:
        places = places.head(limit)
    remaining = len(places)

    def stop_handler(signum: int, frame: object) -> None:
        report = metrics.write()
        crawl_progress("youtube_videos", report, remaining, stopped=True)
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, stop_handler)

    with YouTube(language="vi", region="VN") as client:
        for _, row in places.iterrows():
            place = row.to_dict()
            place_id = str(place.get("place_id", ""))
            if not place_id:
                metrics.mark("skipped")
                continue
            if not refresh_success and (place_id in successful or checkpoint.is_success(place_id)):
                metrics.mark("skipped")
                continue
            query = f"{place.get('place_name', '')} {place.get('province_name', '')}".strip()
            try:
                records = crawl_place(client, place, max_videos)
                new_records = []
                for record in records:
                    key = (str(record["place_id"]), str(record["video_id"]))
                    if key not in existing_keys:
                        existing_keys.add(key)
                        new_records.append(record)
                _append(new_records, YOUTUBE_VIDEOS_FILE, VIDEO_COLUMNS)
                bronze_videos.write(new_records)
                log_row = {**place, "query": query, "status": "success", "video_count": len(new_records),
                           "error_message": "", "crawled_at": pd.Timestamp.utcnow().isoformat()}
                _append([log_row], YOUTUBE_CRAWL_LOG_FILE, LOG_COLUMNS)
                bronze_log.write([log_row], source_id=place_id)
                checkpoint.mark(place_id, "SUCCESS")
                metrics.mark("success")
            except Exception as error:
                log_row = {**place, "query": query, "status": "failed", "video_count": 0,
                           "error_message": str(error), "crawled_at": pd.Timestamp.utcnow().isoformat()}
                _append([log_row], YOUTUBE_CRAWL_LOG_FILE, LOG_COLUMNS)
                bronze_log.write([log_row], source_id=place_id)
                checkpoint.mark(place_id, "FAILED", error_message=str(error))
                metrics.mark("failed")
            remaining -= 1
            report = metrics.write()
            crawl_progress("youtube_videos", report, remaining)
            time.sleep(delay_seconds)
    report = metrics.write()
    if report["failed"]:
        raise RuntimeError(f"YouTube videos had {report['failed']} failed places")


if __name__ == "__main__":
    run()