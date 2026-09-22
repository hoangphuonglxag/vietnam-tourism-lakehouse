from __future__ import annotations


SUCCESS = "SUCCESS"
FAILED_SEARCH = "FAILED_SEARCH"
FAILED_RATE_LIMIT = "FAILED_RATE_LIMIT"
FAILED_DATA = "FAILED_DATA"
FAILED_UNKNOWN = "FAILED_UNKNOWN"


def is_success_status(value: object) -> bool:
    return str(value or "").upper().startswith("SUCCESS")


def classify_error(error: Exception) -> str:
    message = str(error).lower()
    error_name = type(error).__name__.lower()
    if any(token in message or token in error_name for token in ("429", "rate", "too many requests")):
        return FAILED_RATE_LIMIT
    if any(token in message or token in error_name for token in ("csv", "column", "keyerror", "valueerror")):
        return FAILED_DATA
    if any(token in message or token in error_name for token in ("connection", "timeout", "network", "http")):
        return FAILED_SEARCH
    return FAILED_UNKNOWN