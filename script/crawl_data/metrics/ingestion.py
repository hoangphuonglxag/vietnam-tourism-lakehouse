from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from ..config import METRICS_ROOT, RUNS_ROOT

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
    def __init__(
        self,
        source: str,
        run_id: str,
        context: dict[str, object] | None = None,
    ):
        self.source = source
        self.run_id = run_id
        self.context = dict(context or {})
        self.started_at_utc = datetime.now(timezone.utc).isoformat()
        self._started = perf_counter()
        self._counts: Counter[str] = Counter()
        self._final_status = "running"

    def mark(self, status: str) -> None:
        self._counts[status] += 1

    def add(self, name: str, value: int) -> None:
        self._counts[name] += value

    def write(self) -> dict[str, object]:
        status_names = ("success", "failed", "skipped", "quarantine", "retry", "empty")
        total = sum(self._counts[name] for name in status_names)
        report: dict[str, object] = {
            "source": self.source,
            "run_id": self.run_id,
            "run_status": self._final_status,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(perf_counter() - self._started, 3),
            "total": total,
            "success": self._counts["success"],
            "failed": self._counts["failed"],
            "skipped": self._counts["skipped"],
            "quarantine": self._counts["quarantine"],
            "retry": self._counts["retry"],
            "empty": self._counts["empty"],
            "reviews_found": self._counts["reviews_found"],
            "new_reviews": self._counts["new_reviews"],
            "empty_reviews": self._counts["empty_reviews"],
            "success_rate": self._counts["success"] / total if total else 1.0,
            **self.context,
        }
        METRICS_ROOT.mkdir(parents=True, exist_ok=True)
        targets = (
            METRICS_ROOT / f"{self.source}-{self.run_id}.json",
            RUNS_ROOT / f"{self.source}-{self.run_id}.json",
        )
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomically(target, report)
        print(f"INGESTION_METRICS {json.dumps(report, ensure_ascii=False)}")
        return report

    def finish(self, status: str | None = None) -> dict[str, object]:
        if status is None:
            status = "failed" if self._counts["failed"] else "success"
        self._final_status = status
        return self.write()


def _write_json_atomically(target: Path, report: dict[str, object]) -> None:
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(target)