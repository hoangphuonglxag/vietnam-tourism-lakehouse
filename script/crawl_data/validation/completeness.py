from __future__ import annotations

from collections.abc import Iterable, Mapping


def completeness_ratio(rows: Iterable[Mapping[str, object]], field: str) -> float:
    rows = list(rows)
    if not rows:
        return 1.0
    present = sum(1 for row in rows if row.get(field) not in (None, ""))
    return present / len(rows)