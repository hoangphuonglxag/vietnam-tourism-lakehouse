from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = PROJECT_ROOT / "data"
import json
from collections.abc import Mapping

from ..config import (
    TOURISM_RULE_VERSION,
    DIRECT_TOURISM,
    DIRECT_NATURAL,
    DIRECT_HISTORIC,
    CONDITIONAL_TAGS,
    SUPPORTING_EVIDENCE_FIELDS,
    BUSINESS_EXCLUSION_FIELDS,
    EXCLUDED_AMENITIES,
    DIRECT_LEISURE,
    TOURISM_REQUIRED_VALIDATION_STATUS,
)

def _text(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if value is None:
        return ""

    normalized = str(value).strip()
    return (
        ""
        if normalized.lower() in {"", "nan", "none", "<na>"}
        else normalized
    )


def _tags(row: Mapping[str, object]) -> tuple[dict[str, str], bool]:
    tags: dict[str, str] = {}
    raw_tags = _text(row, "tags_json")
    malformed = False

    if raw_tags:
        try:
            parsed = json.loads(raw_tags)

            if isinstance(parsed, dict):
                tags = {
                    str(key): str(value).strip()
                    for key, value in parsed.items()
                    if value is not None and str(value).strip()
                }
            else:
                malformed = True

        except json.JSONDecodeError:
            malformed = True

    for key in ("tourism", "natural", "historic", "leisure"):
        value = _text(row, key)
        if value:
            tags.setdefault(key, value)

    return tags, malformed


def evaluate_tourism_eligibility(
    row: Mapping[str, object],
) -> dict[str, object]:
    tags, malformed_tags = _tags(row)

    evidence = [
        field
        for field in SUPPORTING_EVIDENCE_FIELDS
        if _text(row, field) or tags.get(field)
    ]

    def result(
        status: str,
        reason: str,
        evidence_value: str = "",
        confidence: str = "high",
    ) -> dict[str, object]:
        return {
            "tourism_status": status,
            "tourism_reason": reason,
            "tourism_evidence": evidence_value,
            "tourism_confidence": confidence,
            "tourism_rule_version": TOURISM_RULE_VERSION,
        }

    if malformed_tags:
        return result(
            "review",
            "malformed_tags_json",
            "tags_json",
            "low",
        )

    if (
        any(tags.get(field) for field in BUSINESS_EXCLUSION_FIELDS)
        or tags.get("amenity") in EXCLUDED_AMENITIES
    ) and tags.get("tourism") not in DIRECT_TOURISM:
        excluded = [
            field
            for field in (*BUSINESS_EXCLUSION_FIELDS, "amenity")
            if tags.get(field)
        ]

        return result(
            "rejected",
            "non_destination_business",
            ",".join(excluded),
        )

    direct_tag = next(
        (
            (key, tags[key])
            for key, accepted in (
                ("tourism", DIRECT_TOURISM),
                ("natural", DIRECT_NATURAL),
                ("historic", DIRECT_HISTORIC),
            )
            if tags.get(key) in accepted
        ),
        None,
    )

    if direct_tag or tags.get("leisure") in DIRECT_LEISURE:
        selected = direct_tag or ("leisure", tags["leisure"])

        return result(
            "eligible",
            "strong_tourism_tag",
            f"{selected[0]}={selected[1]}",
        )

    conditional_tag = next(
        (
            (key, value)
            for key, value in sorted(CONDITIONAL_TAGS)
            if tags.get(key) == value
        ),
        None,
    )

    if conditional_tag and evidence:
        return result(
            "eligible",
            "conditional_tag_with_independent_evidence",
            (
                f"{conditional_tag[0]}={conditional_tag[1]};"
                f"{','.join(evidence)}"
            ),
            "medium",
        )

    if conditional_tag:
        return result(
            "review",
            "conditional_tag_needs_evidence",
            f"{conditional_tag[0]}={conditional_tag[1]}",
            "low",
        )

    return result(
        "rejected",
        "no_supported_tourism_signal",
    )


def is_crawl_eligible(row: Mapping[str, object]) -> bool:
    """Return whether a validated place can be crawled automatically."""
    eligibility = evaluate_tourism_eligibility(row)

    return (
        _text(row, "validation_status")
        == TOURISM_REQUIRED_VALIDATION_STATUS
        and eligibility["tourism_status"] == "eligible"
    )

def _read(name: str) -> pd.DataFrame:
    path = DATA_ROOT / name
    if not path.exists():
        raise RuntimeError(f"Missing quality-gate input: {path}")
    data = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    if data.empty:
        raise RuntimeError(f"Quality-gate input is empty: {path}")
    return data


def _require(data: pd.DataFrame, fields: set[str], name: str) -> None:
    missing = sorted(fields - set(data.columns))
    if missing:
        raise RuntimeError(f"{name} is missing columns: {missing}")


def check(stage: str) -> None:
    if stage == "provinces":
        data = _read("provinces.csv")
        _require(data, {"province_id", "province_name", "min_lon", "min_lat", "max_lon", "max_lat"}, stage)
        if data["province_id"].duplicated().any():
            raise RuntimeError("provinces contains duplicate province_id")
        for field in ("min_lon", "min_lat", "max_lon", "max_lat"):
            if pd.to_numeric(data[field], errors="coerce").isna().any():
                raise RuntimeError(f"provinces has invalid numeric field: {field}")
        if (pd.to_numeric(data["min_lon"]) > pd.to_numeric(data["max_lon"])).any():
            raise RuntimeError("provinces has invalid longitude bounds")
        if (pd.to_numeric(data["min_lat"]) > pd.to_numeric(data["max_lat"])).any():
            raise RuntimeError("provinces has invalid latitude bounds")
    elif stage == "candidates":
        data = _read("candidate_places_raw.csv")
        _require(data, {"osm_type", "osm_id", "place_name", "latitude", "longitude", "province_id"}, stage)
        if data.duplicated(["osm_type", "osm_id"]).any():
            raise RuntimeError("candidate_places_raw contains duplicate OSM keys")
    elif stage == "validated":
        data = _read("candidate_places_validated.csv")
        _require(data, {"osm_type", "osm_id", "validation_status", "spatial_status"}, stage)
        allowed = {"valid", "invalid", "review", "quarantine"}
        found = set(data["validation_status"].dropna())
        if not found.issubset(allowed):
            raise RuntimeError(f"candidate_places_validated has unknown statuses: {sorted(found - allowed)}")
    elif stage == "places":
        data = _read("reference/places.csv")
        _require(
            data,
            {
                "place_id", "place_name", "province_id", "latitude", "longitude",
                "validation_status", "tourism_status", "tourism_reason",
                "crawl_eligible", "tourism_rule_version",
            },
            stage,
        )
        if data["place_id"].duplicated().any():
            raise RuntimeError("places contains duplicate place_id")
        required_values = {
            "place_id", "place_name", "province_id", "validation_status",
            "tourism_status", "tourism_reason", "crawl_eligible",
            "tourism_rule_version",
        }
        for field in required_values:
            values = data[field].fillna("").astype(str).str.strip()
            if values.eq("").any():
                raise RuntimeError(f"places has empty values in required field: {field}")
        allowed_validation_statuses = {"valid", "invalid", "review", "quarantine"}
        found_validation_statuses = set(data["validation_status"].str.lower())
        if not found_validation_statuses.issubset(allowed_validation_statuses):
            raise RuntimeError(
                f"places has unknown validation statuses: "
                f"{sorted(found_validation_statuses - allowed_validation_statuses)}"
            )
        allowed_tourism_statuses = {"eligible", "review", "rejected"}
        found_tourism_statuses = set(data["tourism_status"].str.lower())
        if not found_tourism_statuses.issubset(allowed_tourism_statuses):
            raise RuntimeError(
                f"places has unknown tourism statuses: "
                f"{sorted(found_tourism_statuses - allowed_tourism_statuses)}"
            )
        eligible_values = data["crawl_eligible"].str.lower()
        if not eligible_values.isin({"true", "false", "1", "0", "yes", "no"}).all():
            raise RuntimeError("places has invalid crawl_eligible values")
        eligible = eligible_values.isin({"true", "1", "yes"})
        expected_eligible = (
            data["tourism_status"].str.lower().eq("eligible")
            & data["validation_status"].str.lower().eq("valid")
        )
        if eligible.ne(expected_eligible).any():
            raise RuntimeError(
                "places crawl_eligible does not match technical and tourism statuses"
            )
        latitude = pd.to_numeric(data["latitude"], errors="coerce")
        longitude = pd.to_numeric(data["longitude"], errors="coerce")
        if latitude.isna().any() or (~latitude.between(-90, 90)).any():
            raise RuntimeError("places contains invalid latitude")
        if longitude.isna().any() or (~longitude.between(-180, 180)).any():
            raise RuntimeError("places contains invalid longitude")
    else:
        raise ValueError(f"Unknown quality-gate stage: {stage}")
    print(f"QUALITY_GATE_OK stage={stage} rows={len(data)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("provinces", "candidates", "validated", "places"))
    check(parser.parse_args().stage)