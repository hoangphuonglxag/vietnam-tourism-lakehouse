from datetime import datetime
import sys

from airflow import DAG
from airflow.operators.bash import BashOperator

PROJECT_DIR = "/opt/airflow/project"
sys.path.insert(0, PROJECT_DIR)
from script.crawl_data.alerts.discord import dag_success, task_failure


PYTHON_ENV = f"export PYTHONPATH={PROJECT_DIR}:${{PYTHONPATH:-}}"


def job_command(module: str, exports: tuple[str, ...] = ()) -> str:
    lines = ["set -euo pipefail", f"cd {PROJECT_DIR}", PYTHON_ENV]
    lines.extend(exports)
    lines.append(f"python -m {module}")
    return "\n".join(lines)


with DAG(
    dag_id="tourism_social_ingestion",
    description="Frequent Google Maps and YouTube ingestion from the curated place master",
    start_date=datetime(2026, 1, 1),
    schedule="0 3 * * 1",
    catchup=False,
    max_active_runs=1,
    tags=["tourism", "social", "bronze"],
    on_failure_callback=task_failure,
    on_success_callback=dag_success,
    default_args={"on_failure_callback": task_failure},
) as dag:
    backfill = BashOperator(
        task_id="backfill_historical_to_bronze",
        bash_command=job_command("script.crawl_data.backfill_historical"),
    )
    google_ratings = BashOperator(
        task_id="crawl_google_maps_ratings",
        bash_command=job_command(
            "script.crawl_data.jobs.google_maps_ratings",
            (
                "export HEADLESS=true",
                "export TLCN_REFRESH_SUCCESS={{ dag_run.conf.get('refresh_success', 'false') if dag_run else 'false' }}",
                "export GOOGLE_MAPS_DELAY_SECONDS=${GOOGLE_MAPS_DELAY_SECONDS:-1.0}",
            ),
        ),
    )
    google_reviews = BashOperator(
        task_id="crawl_google_maps_reviews",
        bash_command=job_command(
            "script.crawl_data.jobs.google_maps_reviews",
            (
                "export HEADLESS=true",
                "export TLCN_REFRESH_SUCCESS={{ dag_run.conf.get('refresh_success', 'false') if dag_run else 'false' }}",
                "export GOOGLE_MAPS_REVIEWS_DELAY_SECONDS=${GOOGLE_MAPS_REVIEWS_DELAY_SECONDS:-1.0}",
            ),
        ),
    )
    youtube_videos = BashOperator(
        task_id="crawl_youtube_videos",
        bash_command=job_command(
            "script.crawl_data.jobs.youtube_videos",
            ("export TLCN_REFRESH_SUCCESS={{ dag_run.conf.get('refresh_success', 'false') if dag_run else 'false' }}",),
        ),
    )
    youtube_comments = BashOperator(
        task_id="crawl_youtube_comments",
        bash_command=job_command(
            "script.crawl_data.jobs.youtube_comments",
            ("export TLCN_REFRESH_SUCCESS={{ dag_run.conf.get('refresh_success', 'false') if dag_run else 'false' }}",),
        ),
    )
    backfill >> [google_ratings, google_reviews, youtube_videos]
    youtube_videos >> youtube_comments
