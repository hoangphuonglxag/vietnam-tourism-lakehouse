from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import (
    DEFAULT_FRESHNESS_DAYS,
    GOOGLE_MAPS_RATINGS_FILE,
    GOOGLE_MAPS_REVIEWS_FILE,
    PLACES_CATEGORIES_FILE,
    PLACES_FILE,
    PLACE_TAXONOMY_FILE,
    PLANS_ROOT,
    YOUTUBE_COMMENTS_CRAWL_LOG_FILE,
    YOUTUBE_COMMENTS_FILE,
    YOUTUBE_CRAWL_LOG_FILE,
    YOUTUBE_VIDEOS_FILE,
)
from ..validation.tourism import evaluate_tourism_eligibility
from .ingestion import CheckpointStore
from .region_priority import filter_places
from .status import is_success_status


_OPERATIONS = {
    "ratings": "google_ratings",
    "reviews": "google_reviews",
    "videos": "youtube_videos",
    "comments": "youtube_comments",
}
_AIRFLOW_TASKS = {
    "google_ratings": "crawl_google_maps_ratings",
    "google_reviews": "crawl_google_maps_reviews",
    "youtube_videos": "crawl_youtube_videos",
    "youtube_comments": "crawl_youtube_comments",
}
_OPERATION_STATE = {
    "ratings": "google_maps/ratings",
    "reviews": "google_maps/reviews",
    "videos": "youtube/crawl_log",
    "comments": "youtube/comments_crawl_log",
}
_OPERATION_HISTORY = {
    "ratings": (GOOGLE_MAPS_RATINGS_FILE, "place_id", "crawled_at", "crawl_status"),
    "reviews": (GOOGLE_MAPS_REVIEWS_FILE, "place_id", "crawled_at_utc", None),
    "videos": (YOUTUBE_CRAWL_LOG_FILE, "place_id", "crawled_at", "status"),
    "comments": (YOUTUBE_COMMENTS_CRAWL_LOG_FILE, "video_id", "crawled_at", "status"),
}
_OPERATION_DATA = {
    "ratings": GOOGLE_MAPS_RATINGS_FILE,
    "reviews": GOOGLE_MAPS_REVIEWS_FILE,
    "videos": YOUTUBE_VIDEOS_FILE,
    "comments": YOUTUBE_COMMENTS_FILE,
}


def _normalize(value: object) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    without_marks = without_marks.replace("đ", "d").replace("Đ", "D")
    return re.sub(r"[^a-z0-9]+", " ", without_marks.casefold()).strip()


def _request_values(request: dict[str, Any], field: str, plural_field: str) -> list[str]:
    raw = request.get(plural_field)
    if raw is None:
        raw = request.get(field)
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    if not values or any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{plural_field} must contain non-empty strings")
    normalized = list(dict.fromkeys(value.strip() for value in values))
    return normalized


def _reference_version() -> str:
    digest = hashlib.sha256()
    for path in (PLACES_FILE, PLACES_CATEGORIES_FILE, PLACE_TAXONOMY_FILE):
        digest.update(path.name.encode("utf-8"))
        if path.exists():
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(b"missing")
    return digest.hexdigest()


def _requested_datasets(raw: object) -> list[str]:
    if raw is None:
        return list(_OPERATIONS)
    if not isinstance(raw, list) or not raw:
        raise ValueError("datasets must be a non-empty list")
    aliases = {
        "google_ratings": "ratings",
        "google_reviews": "reviews",
        "youtube_videos": "videos",
        "youtube_comments": "comments",
    }
    normalized = []
    for item in raw:
        dataset = aliases.get(str(item).strip().lower(), str(item).strip().lower())
        if dataset not in _OPERATIONS:
            raise ValueError(f"Unsupported dataset in crawl request: {item!r}")
        if dataset not in normalized:
            normalized.append(dataset)
    return [dataset for dataset in _OPERATIONS if dataset in normalized]


def _parse_bool(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    raise ValueError(f"{name} must be a boolean")


def _freshness_settings(request: dict[str, Any], datasets: list[str]) -> dict[str, int]:
    override = request.get("freshness_days", {})
    if isinstance(override, int):
        override = {dataset: override for dataset in datasets}
    if not isinstance(override, dict):
        raise ValueError("freshness_days must be an integer or a dataset-to-days object")
    result: dict[str, int] = {}
    for dataset in datasets:
        days = override.get(dataset, DEFAULT_FRESHNESS_DAYS[dataset])
        if isinstance(days, bool) or not isinstance(days, int) or days < 0:
            raise ValueError(f"freshness_days[{dataset!r}] must be a non-negative integer")
        result[dataset] = days
    return result


def _load_category_terms() -> dict[str, str]:
    if not PLACES_CATEGORIES_FILE.exists() or not PLACE_TAXONOMY_FILE.exists():
        return {}
    categories = pd.read_csv(PLACES_CATEGORIES_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    taxonomy = pd.read_csv(PLACE_TAXONOMY_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    if not {"place_id", "category_id"}.issubset(categories.columns):
        return {}
    if not {"category_id", "category", "subcategory", "group"}.issubset(taxonomy.columns):
        return {}
    taxonomy_fields = [
        field for field in ("group", "category", "subcategory", "name_vi", "name_en")
        if field in taxonomy.columns
    ]
    merged = categories[["place_id", "category_id"]].merge(
        taxonomy[["category_id", *taxonomy_fields]],
        on="category_id",
        how="left",
    )
    return {
        str(place_id): "|".join(
            str(value)
            for value in group[taxonomy_fields].to_numpy().ravel()
            if str(value).strip()
        )
        for place_id, group in merged.groupby("place_id", sort=False)
    }


def _known_category_terms() -> set[str]:
    if not PLACE_TAXONOMY_FILE.exists():
        return set()
    taxonomy = pd.read_csv(PLACE_TAXONOMY_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    return {
        _normalize(value)
        for field in ("group", "category", "subcategory", "name_vi", "name_en")
        if field in taxonomy.columns
        for value in taxonomy[field]
        if _normalize(value)
    }


def _load_places(request: dict[str, Any]) -> pd.DataFrame:
    if not PLACES_FILE.exists():
        raise FileNotFoundError(f"Curated places reference is missing: {PLACES_FILE}")
    places = pd.read_csv(PLACES_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    required = {"place_id", "place_name", "province_id", "province_name"}
    missing = sorted(required - set(places.columns))
    if missing:
        raise ValueError(f"Curated places reference is missing columns: {missing}")

    if "validation_status" in places:
        places = places[places["validation_status"].str.lower() == "valid"]
    if "crawl_eligible" in places:
        places = places[places["crawl_eligible"].str.lower().isin({"true", "1", "yes"})]
    else:
        evaluated = places.apply(evaluate_tourism_eligibility, axis=1)
        places = places[
            evaluated.map(lambda item: item["tourism_status"] == "eligible").to_numpy()
        ]
    category_source = places.copy()

    provinces = _request_values(request, "province", "provinces")
    if provinces:
        wanted_provinces = {_normalize(value) for value in provinces}
        places = places[
            places["province_id"].map(_normalize).isin(wanted_provinces)
            | places["province_name"].map(_normalize).isin(wanted_provinces)
        ]

    requested_place_ids = _request_values(request, "place_id", "place_ids")
    if requested_place_ids:
        requested = set(requested_place_ids)
        found = set(places["place_id"].astype(str))
        missing = sorted(requested - found)
        if missing:
            raise ValueError(
                "Requested place_ids are missing, outside the selected province/category, "
                f"or not crawl eligible: {missing}"
            )
        places = places[places["place_id"].astype(str).isin(requested)]

    category = request.get("category")
    if category is not None and (not isinstance(category, str) or not category.strip()):
        raise ValueError("category must be a non-empty string when provided")
    if category:
        wanted_category = _normalize(category)
        category_terms = _load_category_terms()
        known_categories = _known_category_terms()
        direct_tag_fields = ("tourism", "natural", "historic", "leisure")
        direct_tag_exists = any(
            field in category_source.columns
            and category_source[field].map(_normalize).eq(wanted_category).any()
            for field in direct_tag_fields
        )
        if wanted_category not in known_categories and not direct_tag_exists:
            raise ValueError(
                f"Category {category!r} is not present in the taxonomy or place tags"
            )
        taxonomy_match = places["place_id"].map(category_terms).fillna("").map(
            lambda value: wanted_category
            in {_normalize(part) for part in re.split(r"[|;,]", value) if _normalize(part)}
        ) if category_terms else pd.Series(False, index=places.index)
        tag_match = pd.Series(False, index=places.index)
        for field in direct_tag_fields:
            if field in places.columns:
                tag_match |= places[field].map(_normalize).eq(wanted_category)
        places = places[taxonomy_match | tag_match]

    places = filter_places(places)
    return places.drop_duplicates(subset=["place_id"], keep="first").reset_index(drop=True)


def _read_history(
    path: Path,
    key_field: str,
    timestamp_field: str,
    status_field: str | None,
    item_ids: list[str] | None = None,
) -> dict[str, datetime]:
    if not path.exists():
        return {}
    data = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    if key_field not in data or timestamp_field not in data:
        return {}
    if item_ids is not None:
        data = data[data[key_field].astype(str).isin(set(item_ids))]
        if data.empty:
            return {}
    if status_field and status_field in data:
        data = data[data[status_field].map(is_success_status)]
    timestamps = pd.to_datetime(data[timestamp_field], utc=True, errors="coerce")
    data = data.assign(_timestamp=timestamps).dropna(subset=["_timestamp"])
    if data.empty:
        return {}
    latest = data.groupby(key_field)["_timestamp"].max()
    return {str(key): value.to_pydatetime() for key, value in latest.items()}


def successful_item_ids(dataset: str, item_ids: list[str]) -> set[str]:
    """Return items whose latest persisted status is successful."""
    path, key_field, _, status_field = _OPERATION_HISTORY[dataset]
    latest_status: dict[str, str] = {}
    if status_field and path.exists():
        data = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
        if key_field in data and status_field in data:
            data = data[data[key_field].astype(str).isin(set(item_ids))]
            data = data.drop_duplicates(key_field, keep="last")
            latest_status = {
                str(row[key_field]): str(row[status_field])
                for _, row in data.iterrows()
            }

    checkpoint = CheckpointStore(_OPERATION_STATE[dataset])
    for item_id in item_ids:
        if item_id not in latest_status:
            event = checkpoint.latest_event(item_id)
            if event:
                latest_status[item_id] = str(event.get("status", ""))
    return {
        item_id for item_id, status in latest_status.items()
        if is_success_status(status)
    }


def _latest_seen(dataset: str, item_ids: list[str]) -> dict[str, datetime]:
    checkpoint = CheckpointStore(_OPERATION_STATE[dataset])
    path, key_field, timestamp_field, status_field = _OPERATION_HISTORY[dataset]
    history = _read_history(path, key_field, timestamp_field, status_field, item_ids)

    # Reviews and comment outputs can provide recency evidence per item even
    # when the older checkpoint format did not record an updated timestamp.
    data_path = _OPERATION_DATA[dataset]
    data_timestamp = {
        "ratings": "crawled_at",
        "reviews": "crawled_at_utc",
        "videos": "crawled_at",
        "comments": "crawled_at_utc",
    }[dataset]
    data_key = "video_id" if dataset == "comments" else "place_id"
    if data_path != path and data_path.exists():
        data_history = _read_history(data_path, data_key, data_timestamp, None, item_ids)
        for key, value in data_history.items():
            if key not in history or value > history[key]:
                history[key] = value

    for item_id in item_ids:
        event = checkpoint.latest_event(item_id)
        if not event or str(event.get("status", "")).upper() not in {"SUCCESS", "EMPTY"}:
            continue
        updated = pd.to_datetime(event.get("updated_at_utc"), utc=True, errors="coerce")
        if not pd.isna(updated):
            value = updated.to_pydatetime()
            if item_id not in history or value > history[item_id]:
                history[item_id] = value
    return history


def _is_fresh(value: datetime | None, interval_days: int, now: datetime) -> bool:
    return bool(
        value
        and interval_days > 0
        and 0 <= (now - value).total_seconds() < interval_days * 86400
    )


def build_crawl_plan(
    request: dict[str, Any] | None = None,
    *,
    run_id: str,
    output_dir: Path = PLANS_ROOT,
) -> Path:
    """Build and persist a deterministic, auditable plan without running crawlers."""
    request = dict(request or {})
    datasets = _requested_datasets(request.get("datasets"))
    freshness = _freshness_settings(request, datasets)
    force_refresh = _parse_bool(
        request.get("force_refresh", request.get("refresh_success", False)),
        "force_refresh",
    )
    dry_run = _parse_bool(request.get("dry_run", False), "dry_run")
    places = _load_places(request)
    place_ids = places["place_id"].astype(str).tolist()
    now = datetime.now(timezone.utc)
    scheduled: list[str] = []
    decisions: dict[str, dict[str, object]] = {}
    video_operation_scheduled = False

    for dataset in datasets:
        if dataset == "comments":
            data_path = YOUTUBE_VIDEOS_FILE
            if not data_path.exists():
                candidates: list[str] = []
                existing_video_ids: list[str] = []
                reason = "youtube_video_snapshot_missing"
            else:
                videos = pd.read_csv(data_path, dtype=str, encoding="utf-8-sig").fillna("")
                if not {"video_id", "place_id"}.issubset(videos.columns):
                    raise ValueError(f"YouTube videos file has an invalid schema: {data_path}")
                videos = videos[videos["place_id"].astype(str).isin(place_ids)]
                candidates = videos["video_id"].astype(str).drop_duplicates().tolist()
                existing_video_ids = list(candidates)
                reason = "no_videos_in_scope"
            if candidates:
                latest = _latest_seen("comments", candidates)
                successful = successful_item_ids("comments", candidates)
                item_ids = [
                    item_id for item_id in candidates
                    if force_refresh or (
                        item_id not in successful
                        and not _is_fresh(latest.get(item_id), freshness[dataset], now)
                    )
                ]
                reason = "stale_or_missing_items" if item_ids else (
                    "all_items_successful"
                    if candidates and set(candidates).issubset(successful)
                    else "all_items_fresh"
                )
            else:
                item_ids = []
            include_new_videos = video_operation_scheduled and bool(place_ids)
            should_run = bool(item_ids or include_new_videos)
            operation = _OPERATIONS[dataset]
            decisions[dataset] = {
                "operation": operation,
                "should_run": should_run and not dry_run,
                "would_run": should_run,
                "reason": "dry_run" if dry_run and should_run else reason,
                "item_type": "video",
                "item_ids": item_ids,
                "existing_video_ids": existing_video_ids,
                "place_ids": place_ids if include_new_videos else [],
                "include_new_videos": include_new_videos,
                "freshness_days": freshness[dataset],
            }
        else:
            latest = _latest_seen(dataset, place_ids)
            item_ids = [
                place_id for place_id in place_ids
                if force_refresh
                or not _is_fresh(latest.get(place_id), freshness[dataset], now)
            ]
            should_run = bool(item_ids)
            operation = _OPERATIONS[dataset]
            decisions[dataset] = {
                "operation": operation,
                "should_run": should_run and not dry_run,
                "would_run": should_run,
                "reason": "dry_run" if dry_run and should_run else (
                    "stale_or_missing_items" if should_run else "all_items_fresh"
                ),
                "item_type": "place",
                "item_ids": item_ids,
                "place_ids": item_ids,
                "freshness_days": freshness[dataset],
            }
            if dataset == "videos":
                video_operation_scheduled = should_run and not dry_run

        if decisions[dataset]["should_run"]:
            scheduled.append(str(decisions[dataset]["operation"]))

    plan = {
        "plan_version": 1,
        "run_id": run_id,
        "created_at_utc": now.isoformat(),
        "reference_version": _reference_version(),
        "scope": {
            "province": request.get("provinces", request.get("province")),
            "category": request.get("category"),
            "place_count": len(place_ids),
            "place_ids": place_ids,
        },
        "requested_datasets": datasets,
        "force_refresh": force_refresh,
        "dry_run": dry_run,
        "freshness_days": freshness,
        "decisions": decisions,
        "scheduled_operations": scheduled,
        "would_run_operations": [
            decision["operation"]
            for decision in decisions.values()
            if decision["would_run"]
        ],
    }
    
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_id = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
    target = output_dir / f"crawl-plan-{safe_id}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return target


def load_crawl_plan(path: str | Path | None = None) -> dict[str, Any] | None:
    selected_path = path or os.getenv("TLCN_CRAWL_PLAN_PATH")
    if selected_path is None or not str(selected_path).strip():
        return None
    if str(selected_path).strip().lower() in {"none", "null"}:
        raise ValueError(
            "TLCN_CRAWL_PLAN_PATH contains the literal 'None'/'null'; "
            "verify that build_crawl_plan returned its plan path through XCom"
        )
    target = Path(selected_path)
    if not target.exists():
        raise FileNotFoundError(f"Crawl plan file does not exist: {target}")
    with target.open(encoding="utf-8") as source:
        plan = json.load(source)
    if plan.get("plan_version") not in {1, 2} or not isinstance(plan.get("decisions"), dict):
        raise ValueError(f"Unsupported or malformed crawl plan: {target}")
    return plan


def run_context(plan: dict[str, Any] | None, operation: str) -> dict[str, object]:
    if not plan:
        return {}
    full_scope = plan.get("scope", {})
    scope = {
        key: full_scope.get(key)
        for key in ("province", "category", "place_count")
    }
    return {
        "plan_id": plan.get("run_id", ""),
        "airflow_run_id": plan.get("run_id", ""),
        "dag_id": "tourism_social_ingestion",
        "operation": operation,
        "task_id": _AIRFLOW_TASKS.get(operation, operation),
        "scope": scope,
        "reference_version": plan.get("reference_version", ""),
    }
