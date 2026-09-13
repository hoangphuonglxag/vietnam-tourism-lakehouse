from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import HISTORICAL_ROOT, PLACES_FILE, REFERENCE_ROOT

POLICY_FILE = REFERENCE_ROOT / "region_crawl_policy.csv"
SCORE_VERSION = "v1-place-supply"


def _normalise(series: pd.Series) -> pd.Series:
    maximum = series.max()
    minimum = series.min()
    if pd.isna(maximum) or maximum == minimum:
        return pd.Series(50.0, index=series.index)
    return ((series - minimum) / (maximum - minimum) * 100).round(2)


def build_policy(places_file: Path = PLACES_FILE) -> pd.DataFrame:
    places = pd.read_csv(places_file, dtype=str, encoding="utf-8-sig").fillna("")
    grouped = places.groupby(["province_id", "province_name"], dropna=False).size().reset_index(name="place_count")
    grouped["place_supply_score"] = _normalise(grouped["place_count"])

    ratings_file = HISTORICAL_ROOT / "google_maps_ratings.csv"
    if ratings_file.exists():
        ratings = pd.read_csv(ratings_file, dtype=str, encoding="utf-8-sig").fillna("")
        ratings["google_rating"] = pd.to_numeric(ratings.get("google_rating"), errors="coerce")
        rating_summary = ratings.groupby("province_id")["google_rating"].mean().rename("rating_score")
        grouped = grouped.join(rating_summary, on="province_id")
    grouped["rating_score"] = grouped.get("rating_score", 0).fillna(0)
    grouped["rating_score"] = (grouped["rating_score"] / 5 * 100).clip(0, 100).round(2)

    grouped["potential_score"] = (0.7 * grouped["place_supply_score"] + 0.3 * grouped["rating_score"]).round(2)
    grouped["sample_size"] = grouped["place_count"]
    grouped["confidence"] = grouped["sample_size"].map(lambda value: "low" if value < 20 else "medium" if value < 100 else "high")
    grouped["tier"] = grouped["potential_score"].map(lambda value: "tier_1" if value >= 70 else "tier_2" if value >= 40 else "tier_3")
    grouped["crawl_interval_days"] = grouped["tier"].map({"tier_1": 7, "tier_2": 30, "tier_3": 90})
    grouped["strategic_override"] = False
    grouped["enabled"] = True
    grouped["score_version"] = SCORE_VERSION
    grouped["updated_at_utc"] = pd.Timestamp.utcnow().isoformat()
    return grouped[[
        "province_id", "province_name", "potential_score", "place_supply_score", "rating_score",
        "sample_size", "confidence", "tier", "crawl_interval_days", "strategic_override",
        "enabled", "score_version", "updated_at_utc",
    ]]


def write_policy() -> Path:
    REFERENCE_ROOT.mkdir(parents=True, exist_ok=True)
    policy = build_policy()
    policy.to_csv(POLICY_FILE, index=False, encoding="utf-8-sig")
    return POLICY_FILE


def allowed_tiers() -> set[str]:
    import os
    value = os.getenv("TLCN_CRAWL_TIERS", "tier_1,tier_2,tier_3")
    return {item.strip() for item in value.split(",") if item.strip()}


def filter_places(places: pd.DataFrame) -> pd.DataFrame:
    if not POLICY_FILE.exists() or "province_id" not in places:
        return places
    policy = pd.read_csv(POLICY_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    policy = policy[policy["enabled"].str.lower().isin({"true", "1", "yes"})]
    policy = policy[policy["tier"].isin(allowed_tiers())]
    return places.merge(policy[["province_id"]], on="province_id", how="inner")
