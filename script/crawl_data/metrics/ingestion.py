from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from ..config import METRICS_ROOT

def summarize(*, succeeded: int, failed: int, skipped: int = 0) -> dict[str, int | float]:
    total = succeeded + failed + skipped
    return {
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "total": total,
        "success_rate": succeeded / total if total else 1.0,
    }


class RunMetrics:
    def __init__(self, source: str, run_id: str):
        self.source = source
        self.run_id = run_id
        self.started_at_utc = datetime.now(timezone.utc).isoformat()
        self._started = perf_counter()
        self._counts: Counter[str] = Counter()

    def mark(self, status: str) -> None:
        self._counts[status] += 1

    def write(self) -> dict[str, int | float | str]:
        total = sum(self._counts.values())
        report: dict[str, int | float | str] = {
            "source": self.source,
            "run_id": self.run_id,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(perf_counter() - self._started, 3),
            "total": total,
            "success": self._counts["success"],
            "failed": self._counts["failed"],
            "skipped": self._counts["skipped"],
            "quarantine": self._counts["quarantine"],
            "retry": self._counts["retry"],
            "success_rate": self._counts["success"] / total if total else 1.0,
        }
        METRICS_ROOT.mkdir(parents=True, exist_ok=True)
        target = METRICS_ROOT / f"{self.source}-{self.run_id}.json"
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"INGESTION_METRICS {json.dumps(report, ensure_ascii=False)}")
        return report