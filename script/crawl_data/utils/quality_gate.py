from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"


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
        _require(data, {"place_id", "place_name", "province_id", "latitude", "longitude", "validation_status"}, stage)
        if data["place_id"].duplicated().any():
            raise RuntimeError("places contains duplicate place_id")
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