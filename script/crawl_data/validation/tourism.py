from __future__ import annotations

import json
from collections.abc import Mapping


TOURISM_RULE_VERSION = "tourism-eligibility-v1"

_DIRECT_TOURISM = {
    "aquarium",
    "hotel",
    "museum",
    "resort",
    "theme_park",
    "viewpoint",
    "zoo",
}
_DIRECT_NATURAL = {"beach", "cave_entrance", "waterfall"}
_DIRECT_HISTORIC = {
    "archaeological_site",
    "castle",
    "fort",
    "monument",
    "ruins",
}
_CONDITIONAL_TAGS = {
    ("tourism", "attraction"),
    ("tourism", "artwork"),
    ("tourism", "gallery"),
    ("tourism", "arts_centre"),
    ("natural", "cape"),
    ("natural", "peak"),
    ("historic", "building"),
    ("historic", "memorial"),
    ("leisure", "garden"),
    ("leisure", "park"),
}
_SUPPORTING_EVIDENCE_FIELDS = ("wikidata", "wikipedia", "website", "image")
_BUSINESS_EXCLUSION_FIELDS = ("shop", "craft", "office")


def _text(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if value is None:
        return ""
    normalized = str(value).strip()
    return "" if normalized.lower() in {"", "nan", "none", "<na>"} else normalized


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


def evaluate_tourism_eligibility(row: Mapping[str, object]) -> dict[str, object]:
    """Assess whether an OSM candidate is suitable for automatic tourism crawling."""
    tags, malformed_tags = _tags(row)
    evidence = [
        field
        for field in _SUPPORTING_EVIDENCE_FIELDS
        if _text(row, field) or tags.get(field)
    ]

    if malformed_tags:
        return {
            "tourism_status": "review",
            "tourism_reason": "malformed_tags_json",
            "tourism_evidence": "tags_json",
            "tourism_confidence": "low",
            "tourism_rule_version": TOURISM_RULE_VERSION,
        }

    if (
        any(tags.get(field) for field in _BUSINESS_EXCLUSION_FIELDS)
        or tags.get("amenity") in {"convenience", "copyshop"}
    ) and tags.get("tourism") not in _DIRECT_TOURISM:
        return {
            "tourism_status": "rejected",
            "tourism_reason": "non_destination_business",
            "tourism_evidence": ",".join(
                field for field in (*_BUSINESS_EXCLUSION_FIELDS, "amenity") if tags.get(field)
            ),
            "tourism_confidence": "high",
            "tourism_rule_version": TOURISM_RULE_VERSION,
        }

    direct_tag = next(
        (
            (key, tags[key])
            for key, accepted in (
                ("tourism", _DIRECT_TOURISM),
                ("natural", _DIRECT_NATURAL),
                ("historic", _DIRECT_HISTORIC),
            )
            if tags.get(key) in accepted
        ),
        None,
    )
    if direct_tag or tags.get("leisure") == "water_park":
        selected = direct_tag or ("leisure", "water_park")
        return {
            "tourism_status": "eligible",
            "tourism_reason": "strong_tourism_tag",
            "tourism_evidence": f"{selected[0]}={selected[1]}",
            "tourism_confidence": "high",
            "tourism_rule_version": TOURISM_RULE_VERSION,
        }

    conditional_tag = next(
        (
            (key, value)
            for key, value in sorted(_CONDITIONAL_TAGS)
            if tags.get(key) == value
        ),
        None,
    )
    if conditional_tag and evidence:
        return {
            "tourism_status": "eligible",
            "tourism_reason": "conditional_tag_with_independent_evidence",
            "tourism_evidence": f"{conditional_tag[0]}={conditional_tag[1]};{','.join(evidence)}",
            "tourism_confidence": "medium",
            "tourism_rule_version": TOURISM_RULE_VERSION,
        }
    if conditional_tag:
        return {
            "tourism_status": "review",
            "tourism_reason": "conditional_tag_needs_evidence",
            "tourism_evidence": f"{conditional_tag[0]}={conditional_tag[1]}",
            "tourism_confidence": "low",
            "tourism_rule_version": TOURISM_RULE_VERSION,
        }

    return {
        "tourism_status": "rejected",
        "tourism_reason": "no_supported_tourism_signal",
        "tourism_evidence": "",
        "tourism_confidence": "high",
        "tourism_rule_version": TOURISM_RULE_VERSION,
    }
