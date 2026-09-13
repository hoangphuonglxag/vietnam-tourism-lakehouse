from datetime import datetime
import sys

from airflow import DAG
from airflow.operators.bash import BashOperator

PROJECT_DIR = "/opt/airflow/project"
sys.path.insert(0, PROJECT_DIR)
from script.crawl_data.alerts.discord import dag_success, task_failure


PYTHON_ENV = f"export PYTHONPATH={PROJECT_DIR}:${{PYTHONPATH:-}}"


def python_module(module: str) -> str:
    return f"set -euo pipefail\ncd {PROJECT_DIR}\n{PYTHON_ENV}\npython -m {module}"


def quality_gate(stage: str) -> str:
    return python_module(f"script.crawl_data.quality_gate {stage}")


with DAG(
    dag_id="tourism_ingestion_pipeline",
    description="Province boundaries -> OSM places -> validation/classification -> social ingestion -> Bronze",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["tourism", "ingestion", "bronze"],
    on_failure_callback=task_failure,
    on_success_callback=dag_success,
    default_args={"on_failure_callback": task_failure},
) as dag:
    crawl_provinces = BashOperator(
        task_id="crawl_provinces",
        bash_command=python_module("script.crawl_data.crawl_province"),
    )
    validate_provinces = BashOperator(
        task_id="quality_gate_provinces",
        bash_command=quality_gate("provinces"),
    )
    crawl_candidates = BashOperator(
        task_id="crawl_candidate_places",
        bash_command=python_module("script.crawl_data.crawl_candidate_places_raw"),
    )
    validate_candidates = BashOperator(
        task_id="quality_gate_candidates",
        bash_command=quality_gate("candidates"),
    )
    spatial_validate = BashOperator(
        task_id="validate_places_spatially",
        bash_command=python_module("script.crawl_data.validate_places"),
    )
    validate_validated = BashOperator(
        task_id="quality_gate_validated_places",
        bash_command=quality_gate("validated"),
    )
    classify_places = BashOperator(
        task_id="classify_places",
        bash_command=python_module("script.crawl_data.classify_places"),
    )
    validate_dimension = BashOperator(
        task_id="quality_gate_places_dimension",
        bash_command=quality_gate("places"),
    )
    backfill_bronze = BashOperator(
        task_id="backfill_historical_to_bronze",
        bash_command=python_module("script.crawl_data.backfill_historical"),
    )
    google_ratings = BashOperator(
        task_id="crawl_google_maps_ratings",
        bash_command=f"set -euo pipefail\nexport HEADLESS=true\ncd {PROJECT_DIR}\n{PYTHON_ENV}\npython -m script.crawl_data.jobs.google_maps_ratings",
    )
    google_reviews = BashOperator(
        task_id="crawl_google_maps_reviews",
        bash_command=f"set -euo pipefail\nexport HEADLESS=true\ncd {PROJECT_DIR}\n{PYTHON_ENV}\npython -m script.crawl_data.jobs.google_maps_reviews",
    )
    youtube_videos = BashOperator(
        task_id="crawl_youtube_videos",
        bash_command=python_module("script.crawl_data.jobs.youtube_videos"),
    )
    youtube_comments = BashOperator(
        task_id="crawl_youtube_comments",
        bash_command=python_module("script.crawl_data.jobs.youtube_comments"),
    )
    crawl_provinces >> validate_provinces >> crawl_candidates >> validate_candidates
    validate_candidates >> spatial_validate >> validate_validated >> classify_places >> validate_dimension
    validate_dimension >> backfill_bronze
    backfill_bronze >> [google_ratings, google_reviews, youtube_videos]
    youtube_videos >> youtube_comments
