from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    path = Path(value).expanduser() if value else default
    return path if path.is_absolute() else PROJECT_ROOT / path


DATA_ROOT = _path_from_env("TLCN_DATA_ROOT", PROJECT_ROOT / "data")
BRONZE_ROOT = _path_from_env("TLCN_BRONZE_ROOT", DATA_ROOT / "bronze")
HISTORICAL_ROOT = _path_from_env("TLCN_HISTORICAL_ROOT", DATA_ROOT / "historical")
REFERENCE_ROOT = _path_from_env("TLCN_REFERENCE_ROOT", DATA_ROOT / "reference")

# Canonical inputs and legacy CSV outputs. Jobs own these paths so crawlers
# can be replaced without changing Airflow DAG configuration.
PLACES_FILE = REFERENCE_ROOT / "places.csv"
GOOGLE_MAPS_RATINGS_FILE = HISTORICAL_ROOT / "google_maps_ratings.csv"
GOOGLE_MAPS_REVIEWS_FILE = HISTORICAL_ROOT / "google_maps_reviews.csv"
GOOGLE_MAPS_ERRORS_FILE = HISTORICAL_ROOT / "google_maps_errors.csv"
METRICS_ROOT = BRONZE_ROOT / "_metrics"
YOUTUBE_VIDEOS_FILE = HISTORICAL_ROOT / "youtube_videos.csv"
YOUTUBE_COMMENTS_FILE = HISTORICAL_ROOT / "youtube_comments.csv"
YOUTUBE_CRAWL_LOG_FILE = HISTORICAL_ROOT / "youtube_crawl_log.csv"
YOUTUBE_COMMENTS_CRAWL_LOG_FILE = HISTORICAL_ROOT / "youtube_comments_crawl_log.csv"

def ensure_data_directories() -> None:
    """Create configured data roots at the job boundary."""
    for path in (DATA_ROOT, BRONZE_ROOT, HISTORICAL_ROOT, REFERENCE_ROOT, METRICS_ROOT):
        path.mkdir(parents=True, exist_ok=True)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


# Shared crawler/runtime settings. Environment variables override defaults so
# local runs and Airflow tasks use the same configuration contract.
OVERPASS_URL = os.getenv(
    "OVERPASS_URL",
    "https://overpass-api.de/api/interpreter",
).strip()
PROVINCES_SOURCE_URL = os.getenv(
    "PROVINCES_SOURCE_URL",
    "https://api.github.com/repos/thanglequoc/vietnamese-provinces-database/contents/json/geojson",
).strip()
PROVINCES_RAW_BASE_URL = os.getenv(
    "PROVINCES_RAW_BASE_URL",
    "https://raw.githubusercontent.com/thanglequoc/vietnamese-provinces-database/master/json/geojson",
).strip()
USER_AGENT = os.getenv("TLCN_USER_AGENT", "TLCN-Tourism-Research/1.0").strip()
REQUEST_TIMEOUT_SECONDS = env_int("REQUEST_TIMEOUT_SECONDS", 180)
OVERPASS_TIMEOUT_SECONDS = env_int("OVERPASS_TIMEOUT_SECONDS", 120)
PROVINCE_REQUEST_TIMEOUT_SECONDS = env_int(
    "PROVINCE_REQUEST_TIMEOUT_SECONDS",
    30,
)
MAX_WORKERS = env_int("CRAWL_MAX_WORKERS", 8)
MAX_RETRIES = env_int("CRAWL_MAX_RETRIES", 3)
RETRY_BACKOFF_SECONDS = env_float("CRAWL_RETRY_BACKOFF_SECONDS", 2.0)
REQUEST_JITTER_MIN_SECONDS = env_float("REQUEST_JITTER_MIN_SECONDS", 0.3)
REQUEST_JITTER_MAX_SECONDS = env_float("REQUEST_JITTER_MAX_SECONDS", 1.2)
TEST_MODE = env_bool("TLCN_TEST_MODE", False)
TEST_PROVINCE = os.getenv("TEST_PROVINCE", "Đà Nẵng").strip()
BOUNDARY_REVIEW_DISTANCE_M = env_float("BOUNDARY_REVIEW_DISTANCE_M", 1000.0)