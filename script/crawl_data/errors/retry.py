from __future__ import annotations


RETRYABLE_TYPES = {"transient", "rate_limited"}


def is_retryable(error_type: str, attempt: int, max_attempts: int = 3) -> bool:
    return error_type in RETRYABLE_TYPES and attempt < max_attempts