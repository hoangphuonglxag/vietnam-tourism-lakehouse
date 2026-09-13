from __future__ import annotations

import json
import os
from urllib import request


def send_message(content: str) -> None:
    webhook_url = os.getenv("DISCORD_INGESTION_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return
    payload = json.dumps({"content": content}).encode("utf-8")
    try:
        request.urlopen(
            request.Request(
                webhook_url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "TLCN-Tourism-Lakehouse/1.0",
                },
                method="POST",
            ),
            timeout=10,
        ).close()
    except Exception as error:
        print(f"DISCORD_ALERT_FAILED error={error}", flush=True)


def task_failure(context: dict[str, object]) -> None:
    """Send a compact Airflow task failure alert without masking the failure."""
    webhook_url = os.getenv("DISCORD_INGESTION_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return

    task_instance = context.get("task_instance")
    dag_run = context.get("dag_run")
    dag_id = getattr(task_instance, "dag_id", "unknown")
    task_id = getattr(task_instance, "task_id", "unknown")
    run_id = getattr(dag_run, "run_id", "unknown")
    exception = str(context.get("exception", "unknown error"))

    content = "\n".join(
        (
            "[FAILED] Tourism ingestion task",
            f"dag: {dag_id}",
            f"task: {task_id}",
            f"run: {run_id}",
            f"error: {exception[:1000]}",
        )
    )
    send_message(content)


def dag_success(context: dict[str, object]) -> None:
    """Send one success summary after an Airflow DAG run completes."""
    webhook_url = os.getenv("DISCORD_INGESTION_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return

    dag = context.get("dag")
    dag_run = context.get("dag_run")
    dag_id = getattr(dag, "dag_id", "unknown")
    run_id = getattr(dag_run, "run_id", "unknown")
    content = "\n".join(
        (
            "[SUCCESS] Tourism ingestion DAG",
            f"dag: {dag_id}",
            f"run: {run_id}",
        )
    )
    send_message(content)


def crawl_progress(source: str, report: dict[str, object], remaining: int, stopped: bool = False) -> None:
    processed = int(report.get("total", 0))
    total = processed + remaining
    status = "STOPPED" if stopped else "SUMMARY" if remaining == 0 else "PROGRESS"
    content = "\n".join(
        (
            f"[{status}] {source}",
            f"run: {report.get('run_id', 'unknown')}",
            f"progress: {processed}/{total}",
            f"success: {report.get('success', 0)} | failed: {report.get('failed', 0)}",
            f"remaining: {remaining}",
        )
    )
    print(content, flush=True)
    if stopped or remaining == 0:
        send_message(content)
