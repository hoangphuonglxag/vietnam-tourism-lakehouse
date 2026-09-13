from __future__ import annotations


def valid_rating(value: object) -> bool:
    if value in (None, ""):
        return True
    try:
        return 0 <= float(value) <= 5
    except (TypeError, ValueError):
        return False


def valid_coordinate(latitude: object, longitude: object) -> bool:
    try:
        return -90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180
    except (TypeError, ValueError):
        return False