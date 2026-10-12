from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from script.crawl_data.utils import quality_gate


def _write_places(path: Path, **overrides: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "place_id": "hotel-1",
        "place_name": "Demo Hotel",
        "province_id": "48",
        "latitude": "16.05",
        "longitude": "108.2",
        "validation_status": "valid",
        "tourism_status": "eligible",
        "tourism_reason": "strong_tourism_tag",
        "crawl_eligible": "true",
        "tourism_rule_version": "tourism-eligibility-v1",
    }
    row.update(overrides)
    pd.DataFrame([row]).to_csv(path, index=False, encoding="utf-8-sig")


def test_places_quality_gate_accepts_consistent_eligible_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_places(tmp_path / "reference" / "places.csv")
    monkeypatch.setattr(quality_gate, "DATA_ROOT", tmp_path)

    quality_gate.check("places")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"validation_status": "review"},
            "does not match technical and tourism statuses",
        ),
        (
            {"crawl_eligible": "false"},
            "does not match technical and tourism statuses",
        ),
        ({"tourism_status": ""}, "empty values in required field: tourism_status"),
        ({"crawl_eligible": "maybe"}, "invalid crawl_eligible values"),
    ],
)
def test_places_quality_gate_rejects_inconsistent_eligibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, str],
    message: str,
) -> None:
    _write_places(tmp_path / "reference" / "places.csv", **overrides)
    monkeypatch.setattr(quality_gate, "DATA_ROOT", tmp_path)

    with pytest.raises(RuntimeError, match=message):
        quality_gate.check("places")
