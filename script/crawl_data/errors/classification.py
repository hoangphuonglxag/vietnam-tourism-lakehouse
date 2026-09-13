from __future__ import annotations


def classify(error: BaseException) -> str:
    name = type(error).__name__.lower()
    text = str(error).lower()
    if "timeout" in name or "timeout" in text:
        return "transient"
    if any(token in text for token in ("429", "rate limit", "too many requests")):
        return "rate_limited"
    if isinstance(error, (ValueError, KeyError, FileNotFoundError)):
        return "data_or_configuration"
    return "unknown"