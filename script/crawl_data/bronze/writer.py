from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path


def write_jsonl(rows: Iterable[Mapping[str, object]], target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"Bronze object already exists: {target}")
    with target.open("x", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
    return target