from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from script.crawl_data.utils import crawl_plan, ingestion, region_priority


def test_run_context_uses_airflow_task_id() -> None:
    context = crawl_plan.run_context(
        {
            "run_id": "manual__2026-10-10",
            "scope": {"province": "Đà Nẵng", "category": "hotel", "place_count": 2},
            "reference_version": "abc123",
        },
        "google_ratings",
    )

    assert context["airflow_run_id"] == "manual__2026-10-10"
    assert context["task_id"] == "crawl_google_maps_ratings"
    assert context["scope"] == {
        "province": "Đà Nẵng",
        "category": "hotel",
        "place_count": 2,
    }


def test_load_plan_rejects_literal_none_xcom_value() -> None:
    with pytest.raises(ValueError, match="build_crawl_plan returned its plan path through XCom"):
        crawl_plan.load_crawl_plan("None")


def test_successful_item_ids_uses_latest_status_and_checkpoint_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = tmp_path / "comments.csv"
    pd.DataFrame(
        [
            {"video_id": "failed-after-success", "status": "SUCCESS"},
            {"video_id": "failed-after-success", "status": "FAILED_SEARCH"},
            {"video_id": "successful-video", "status": "SUCCESS"},
        ]
    ).to_csv(history, index=False, encoding="utf-8-sig")
    monkeypatch.setitem(
        crawl_plan._OPERATION_HISTORY,
        "comments",
        (history, "video_id", "crawled_at", "status"),
    )
    monkeypatch.setattr(ingestion, "BRONZE_ROOT", tmp_path / "bronze")
    ingestion.CheckpointStore("youtube/comments_crawl_log").mark(
        "checkpoint-success", "SUCCESS"
    )

    successful = crawl_plan.successful_item_ids(
        "comments",
        ["failed-after-success", "successful-video", "checkpoint-success"],
    )

    assert successful == {"successful-video", "checkpoint-success"}


def _write_reference(root: Path) -> None:
    reference = root / "reference"
    reference.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "place_id": "hotel-1",
                "place_name": "Demo Hotel",
                "province_id": "48",
                "province_name": "Đà Nẵng",
                "validation_status": "valid",
                "crawl_eligible": "true",
                "tourism": "hotel",
            },
            {
                "place_id": "park-1",
                "place_name": "Neighborhood Park",
                "province_id": "48",
                "province_name": "Đà Nẵng",
                "validation_status": "valid",
                "crawl_eligible": "true",
                "tourism": "park",
            },
            {
                "place_id": "hotel-2",
                "place_name": "Hotel in Hue",
                "province_id": "46",
                "province_name": "Huế",
                "validation_status": "valid",
                "crawl_eligible": "true",
                "tourism": "hotel",
            },
            {
                "place_id": "artwork-1",
                "place_name": "Public Artwork",
                "province_id": "48",
                "province_name": "Đà Nẵng",
                "validation_status": "valid",
                "crawl_eligible": "true",
                "tourism": "artwork",
                "wikidata": "Q12345",
            },
        ]
    ).to_csv(reference / "places.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {
                "place_id": "hotel-1",
                "category_id": "CAT001",
                "group": "accommodation",
                "category": "hotel",
                "subcategory": "hotel",
            },
            {
                "place_id": "park-1",
                "category_id": "CAT002",
                "group": "recreation",
                "category": "park",
                "subcategory": "public_park",
            },
            {
                "place_id": "hotel-2",
                "category_id": "CAT001",
                "group": "accommodation",
                "category": "hotel",
                "subcategory": "hotel",
            },
        ]
    ).to_csv(reference / "place_categories.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {
                "category_id": "CAT001",
                "group": "accommodation",
                "category": "hotel",
                "subcategory": "hotel",
                "name_vi": "Khách sạn",
                "name_en": "Hotel",
            },
            {
                "category_id": "CAT002",
                "group": "recreation",
                "category": "park",
                "subcategory": "public_park",
                "name_vi": "Công viên",
                "name_en": "Public Park",
            },
        ]
    ).to_csv(reference / "taxonomy.csv", index=False, encoding="utf-8-sig")


def test_place_scope_supports_multiple_provinces_and_explicit_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_reference(tmp_path)
    root = tmp_path / "reference"
    monkeypatch.setattr(crawl_plan, "PLACES_FILE", root / "places.csv")
    monkeypatch.setattr(crawl_plan, "PLACES_CATEGORIES_FILE", root / "place_categories.csv")
    monkeypatch.setattr(crawl_plan, "PLACE_TAXONOMY_FILE", root / "taxonomy.csv")
    monkeypatch.setattr(region_priority, "POLICY_FILE", tmp_path / "no-region-policy.csv")

    selected = crawl_plan._load_places(
        {"provinces": ["Đà Nẵng", "46"], "place_ids": ["hotel-1", "hotel-2"]}
    )

    assert selected["place_id"].tolist() == ["hotel-1", "hotel-2"]


def test_category_scope_matches_artwork_osm_tag_without_taxonomy_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_reference(tmp_path)
    root = tmp_path / "reference"
    monkeypatch.setattr(crawl_plan, "PLACES_FILE", root / "places.csv")
    monkeypatch.setattr(crawl_plan, "PLACES_CATEGORIES_FILE", root / "place_categories.csv")
    monkeypatch.setattr(crawl_plan, "PLACE_TAXONOMY_FILE", root / "taxonomy.csv")
    monkeypatch.setattr(region_priority, "POLICY_FILE", tmp_path / "no-region-policy.csv")

    selected = crawl_plan._load_places(
        {"province": "Đà Nẵng", "category": "artwork"}
    )

    assert selected["place_id"].tolist() == ["artwork-1"]


def test_planner_scopes_places_and_skips_successful_comments(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_reference(tmp_path)
    history_dir = tmp_path / "historical"
    history_dir.mkdir()
    video_file = history_dir / "youtube_videos.csv"
    pd.DataFrame(
        [{"place_id": "hotel-1", "video_id": "video-1", "crawled_at": "2026-10-09T00:00:00Z"}]
    ).to_csv(video_file, index=False, encoding="utf-8-sig")

    root = tmp_path / "reference"
    monkeypatch.setattr(crawl_plan, "PLACES_FILE", root / "places.csv")
    monkeypatch.setattr(crawl_plan, "PLACES_CATEGORIES_FILE", root / "place_categories.csv")
    monkeypatch.setattr(crawl_plan, "PLACE_TAXONOMY_FILE", root / "taxonomy.csv")
    monkeypatch.setattr(crawl_plan, "YOUTUBE_VIDEOS_FILE", video_file)
    monkeypatch.setattr(crawl_plan, "YOUTUBE_COMMENTS_CRAWL_LOG_FILE", history_dir / "comments.csv")
    monkeypatch.setattr(crawl_plan, "YOUTUBE_COMMENTS_FILE", history_dir / "comments-data.csv")
    monkeypatch.setattr(crawl_plan, "GOOGLE_MAPS_RATINGS_FILE", history_dir / "ratings.csv")
    monkeypatch.setattr(crawl_plan, "GOOGLE_MAPS_REVIEWS_FILE", history_dir / "reviews.csv")
    monkeypatch.setattr(crawl_plan, "YOUTUBE_CRAWL_LOG_FILE", history_dir / "videos-log.csv")
    monkeypatch.setattr(crawl_plan, "PLANS_ROOT", tmp_path / "plans")
    monkeypatch.setattr(region_priority, "POLICY_FILE", tmp_path / "no-region-policy.csv")
    monkeypatch.setattr(ingestion, "BRONZE_ROOT", tmp_path / "bronze")
    monkeypatch.setattr(crawl_plan, "DEFAULT_FRESHNESS_DAYS", {
        "ratings": 30,
        "reviews": 30,
        "videos": 30,
        "comments": 30,
    })
    monkeypatch.setitem(
        crawl_plan._OPERATION_HISTORY,
        "ratings",
        (history_dir / "ratings.csv", "place_id", "crawled_at", "crawl_status"),
    )
    monkeypatch.setitem(crawl_plan._OPERATION_DATA, "ratings", history_dir / "ratings.csv")
    monkeypatch.setitem(
        crawl_plan._OPERATION_HISTORY,
        "comments",
        (history_dir / "comments.csv", "video_id", "crawled_at", "status"),
    )
    monkeypatch.setitem(crawl_plan._OPERATION_DATA, "comments", history_dir / "comments-data.csv")

    checkpoint = ingestion.CheckpointStore("youtube/comments_crawl_log")
    checkpoint.mark("video-1", "SUCCESS")

    plan_path = crawl_plan.build_crawl_plan(
        {
            "province": "Da Nang",
            "category": "hotel",
            "datasets": ["comments", "ratings"],
            "freshness_days": {"comments": 0, "ratings": 30},
        },
        run_id="test-run",
        output_dir=tmp_path / "plans",
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    assert plan["scope"]["place_ids"] == ["hotel-1"]
    assert plan["decisions"]["comments"]["reason"] == "all_items_successful"
    assert plan["scheduled_operations"] == ["google_ratings"]

    forced_plan_path = crawl_plan.build_crawl_plan(
        {
            "province": "Da Nang",
            "category": "hotel",
            "datasets": ["comments", "ratings"],
            "freshness_days": {"comments": 0, "ratings": 30},
            "force_refresh": True,
        },
        run_id="test-force-refresh",
        output_dir=tmp_path / "plans",
    )
    forced_plan = json.loads(forced_plan_path.read_text(encoding="utf-8"))
    assert forced_plan["decisions"]["comments"]["item_ids"] == ["video-1"]
    assert forced_plan["decisions"]["comments"]["should_run"] is True


def test_dry_run_reports_work_without_scheduling_crawlers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_reference(tmp_path)
    root = tmp_path / "reference"
    monkeypatch.setattr(crawl_plan, "PLACES_FILE", root / "places.csv")
    monkeypatch.setattr(crawl_plan, "PLACES_CATEGORIES_FILE", root / "place_categories.csv")
    monkeypatch.setattr(crawl_plan, "PLACE_TAXONOMY_FILE", root / "taxonomy.csv")
    monkeypatch.setattr(crawl_plan, "GOOGLE_MAPS_RATINGS_FILE", tmp_path / "missing-ratings.csv")
    monkeypatch.setattr(crawl_plan, "PLANS_ROOT", tmp_path / "plans")
    monkeypatch.setitem(
        crawl_plan._OPERATION_HISTORY,
        "ratings",
        (tmp_path / "missing-rating-log.csv", "place_id", "crawled_at", "crawl_status"),
    )
    monkeypatch.setitem(crawl_plan._OPERATION_DATA, "ratings", tmp_path / "missing-ratings.csv")
    monkeypatch.setattr(region_priority, "POLICY_FILE", tmp_path / "no-region-policy.csv")
    monkeypatch.setattr(ingestion, "BRONZE_ROOT", tmp_path / "bronze")

    path = crawl_plan.build_crawl_plan(
        {"province": "Đà Nẵng", "category": "hotel", "datasets": ["ratings"], "dry_run": True},
        run_id="dry-run",
        output_dir=tmp_path / "plans",
    )
    plan = json.loads(path.read_text(encoding="utf-8"))

    assert plan["would_run_operations"] == ["google_ratings"]
    assert plan["scheduled_operations"] == []
    assert plan["decisions"]["ratings"]["should_run"] is False
