from __future__ import annotations

from datetime import datetime, timezone


SCOPE_CURRENT_34 = "current_34"
SCOPE_LEGACY_63 = "legacy_63"

ALLOWED_SCOPES = {
    SCOPE_CURRENT_34,
    SCOPE_LEGACY_63,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_scope(scope: str, config_name: str = "SCOPE") -> str:
    normalized = str(scope).strip().lower()

    if normalized not in ALLOWED_SCOPES:
        raise ValueError(
            f"Invalid {config_name}='{scope}'. "
            f"Allowed values: {sorted(ALLOWED_SCOPES)}"
        )

    return normalized


def log_event(stage: str, message: str, **fields) -> None:
    timestamp = utc_now_iso()

    extras = " ".join(
        f"{key}={value}"
        for key, value in fields.items()
        if value is not None
    )

    if extras:
        print(f"[{timestamp}] [{stage}] {message} | {extras}")
    else:
        print(f"[{timestamp}] [{stage}] {message}")
