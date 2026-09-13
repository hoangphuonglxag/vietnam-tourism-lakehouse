from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping

import pandas as pd
import s3fs

from .bronze.writer import write_jsonl
from .config import BRONZE_ROOT


@dataclass(frozen=True)
class DatasetSpec:
    required: tuple[str, ...] = ()
    numeric_ranges: tuple[tuple[str, float, float], ...] = ()
    non_negative: tuple[str, ...] = ()


DATASET_SPECS = {
    "reference/provinces": DatasetSpec(
        required=("province_id", "province_name", "min_lon", "min_lat", "max_lon", "max_lat"),
        numeric_ranges=(
            ("min_lon", -180, 180), ("min_lat", -90, 90),
            ("max_lon", -180, 180), ("max_lat", -90, 90),
        ),
    ),
    "osm/candidate_places_raw": DatasetSpec(
        required=("osm_type", "osm_id", "place_name", "latitude", "longitude"),
        numeric_ranges=(("latitude", -90, 90), ("longitude", -180, 180)),
    ),
    "osm/candidate_places_validated": DatasetSpec(
        required=("osm_type", "osm_id", "validation_status"),
        numeric_ranges=(("latitude", -90, 90), ("longitude", -180, 180)),
    ),
    "places": DatasetSpec(
        required=("place_id", "place_name", "province_id", "latitude", "longitude", "validation_status"),
        numeric_ranges=(("latitude", -90, 90), ("longitude", -180, 180)),
    ),
    "reference/place_categories": DatasetSpec(required=("place_id", "category_id")),
    "reference/taxonomy": DatasetSpec(required=("category_id", "group", "category")),
    "google_maps/ratings": DatasetSpec(
        required=("place_id", "place_name", "crawl_status", "crawled_at"),
        numeric_ranges=(("google_rating", 0, 5),),
        non_negative=("google_review_count", "rating_1_count", "rating_2_count", "rating_3_count", "rating_4_count", "rating_5_count"),
    ),
    "google_maps/reviews": DatasetSpec(required=("review_id", "place_id", "crawled_at_utc"), numeric_ranges=(("rating", 1, 5),), non_negative=("likes_count",)),
    "google_maps/errors": DatasetSpec(required=("place_id", "error_type", "failed_at")),
    "youtube/videos": DatasetSpec(required=("place_id", "video_id", "crawled_at"), non_negative=("views", "duration_seconds")),
    "youtube/comments": DatasetSpec(required=("place_id", "video_id", "crawled_at_utc"), non_negative=("likes",)),
    "youtube/crawl_log": DatasetSpec(required=("place_id", "query", "status", "crawled_at"), non_negative=("video_count",)),
    "youtube/comments_crawl_log": DatasetSpec(required=("place_id", "video_id", "status", "crawled_at"), non_negative=("comment_count",)),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id(source: str) -> str:
    return f"{source}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"


def _as_number(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quality_errors(row: Mapping[str, object], spec: DatasetSpec) -> list[str]:
    errors: list[str] = []
    for field in spec.required:
        if field not in row or row[field] is None or str(row[field]).strip() == "":
            errors.append(f"missing:{field}")
    for field, minimum, maximum in spec.numeric_ranges:
        value = _as_number(row.get(field))
        if value is not None and not minimum <= value <= maximum:
            errors.append(f"range:{field}")
        if row.get(field) not in (None, "") and value is None:
            errors.append(f"numeric:{field}")
    for field in spec.non_negative:
        value = _as_number(row.get(field))
        if value is not None and value < 0:
            errors.append(f"negative:{field}")
        if row.get(field) not in (None, "") and value is None:
            errors.append(f"numeric:{field}")
    return errors


def _event_time(row: Mapping[str, object]) -> datetime:
    for field in ("crawled_at_utc", "crawled_at", "failed_at", "ingested_at_utc"):
        value = row.get(field)
        if value:
            parsed = pd.to_datetime(value, utc=True, errors="coerce")
            if not pd.isna(parsed):
                return parsed.to_pydatetime()
    return datetime.now(timezone.utc)


class BronzeWriter:
    """Validate and append immutable JSONL Bronze objects for one dataset."""

    def __init__(self, dataset: str, source: str, run_id: str | None = None, pipeline_version: str = "1.0", crawler_version: str = "adapter-1"):
        self.dataset = dataset
        self.source = source
        self.run_id = run_id or new_run_id(source)
        self.pipeline_version = pipeline_version
        self.crawler_version = crawler_version
        self.s3_root = os.getenv("TLCN_BRONZE_S3_URI", "s3://lakehouse/bronze").rstrip("/")
        self.s3 = s3fs.S3FileSystem(
            key=os.getenv("MINIO_ROOT_USER", "lakehouse_admin"),
            secret=os.getenv("MINIO_ROOT_PASSWORD", "minIO123"),
            client_kwargs={
                "endpoint_url": os.getenv("S3_ENDPOINT", "http://localhost:9000"),
                "region_name": os.getenv("AWS_REGION", "us-east-1"),
            },
        )

    def write(self, rows: Iterable[Mapping[str, object]], source_id: str = "", source_url: str = "", attempt: int = 1) -> dict[str, int]:
        spec = DATASET_SPECS.get(self.dataset, DatasetSpec())
        accepted: dict[str, list[dict[str, object]]] = {}
        quarantined: dict[str, list[dict[str, object]]] = {}
        for original in rows:
            row = dict(original)
            errors = _quality_errors(row, spec)
            metadata = {
                "run_id": self.run_id,
                "source": self.source,
                "source_id": source_id or str(row.get("video_id") or row.get("review_id") or row.get("place_id") or ""),
                "source_url": source_url or str(row.get("url") or row.get("google_maps_url") or ""),
                "ingested_at_utc": utc_now(),
                "pipeline_version": self.pipeline_version,
                "crawler_version": self.crawler_version,
                "attempt": attempt,
                "record_status": "quarantine" if errors else "success",
            }
            row.update(metadata)
            if errors:
                row["quality_errors"] = json.dumps(errors)
                target = quarantined.setdefault(_event_time(row).strftime("%Y-%m-%d"), [])
            else:
                target = accepted.setdefault(_event_time(row).strftime("%Y-%m-%d"), [])
            target.append(row)

        for crawl_date, date_rows in accepted.items():
            self._write_partition(self.dataset, crawl_date, date_rows)
        for crawl_date, date_rows in quarantined.items():
            self._write_partition(f"quarantine/{self.dataset}", crawl_date, date_rows)
        return {"success": sum(map(len, accepted.values())), "quarantine": sum(map(len, quarantined.values()))}

    def _write_partition(self, dataset: str, crawl_date: str, rows: list[dict[str, object]]) -> None:
        object_id = uuid.uuid4().hex[:12]
        target = BRONZE_ROOT / dataset / f"crawl_date={crawl_date}" / f"part-{self.run_id}-{object_id}.jsonl"
        write_jsonl(rows, target)
        relative = f"{dataset}/crawl_date={crawl_date}/{target.name}"
        s3_target = f"{self.s3_root}/{relative}".removeprefix("s3://")
        with self.s3.open(s3_target, "w", encoding="utf-8", newline="\n") as file:
            for row in rows:
                file.write(json.dumps(dict(row), ensure_ascii=False) + "\n")


class CheckpointStore:
    """Append-only item state used to resume a crawler after interruption."""

    def __init__(self, dataset: str):
        self.path = BRONZE_ROOT / "_state" / f"{dataset.replace('/', '_')}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._latest: dict[str, str] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    event = json.loads(line)
                    self._latest[str(event["item_key"])] = str(event["status"])

    def is_success(self, item_key: str) -> bool:
        return self._latest.get(str(item_key)) == "SUCCESS"

    def mark(self, item_key: str, status: str, attempt: int = 1, error_message: str = "") -> None:
        event = {
            "item_key": str(item_key),
            "status": status,
            "attempt": attempt,
            "error_message": error_message,
            "updated_at_utc": utc_now(),
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._latest[str(item_key)] = status