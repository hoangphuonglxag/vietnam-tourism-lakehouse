from datetime import datetime
import sys

from airflow import DAG
from airflow.operators.bash import BashOperator

PROJECT_DIR = "/opt/airflow/project"
sys.path.insert(0, PROJECT_DIR)

from script.alerts.discord import dag_success, task_failure


PYTHON_ENV = f"export PYTHONPATH={PROJECT_DIR}:${{PYTHONPATH:-}}"


def module_command(module: str) -> str:
    return (
        "set -euo pipefail\n"
        f"cd {PROJECT_DIR}\n"
        f"{PYTHON_ENV}\n"
        f"python -m {module}"
    )


def gate_command(stage: str) -> str:
    return module_command(
        f"script.crawl_data.utils.quality_gate {stage}"
    )


with DAG(
    dag_id="dag_crawl_reference_backfill_data",
    description="Refresh province boundaries and place reference data",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["tourism", "reference", "places"],
    on_failure_callback=task_failure,
    on_success_callback=dag_success,
    default_args={
        "on_failure_callback": task_failure,
    },
) as dag:

    crawl_provinces = BashOperator(
        task_id="crawl_provinces",
        bash_command=module_command(
            "script.crawl_data.crawl_reference.crawl_province"
        ),
    )

    gate_provinces = BashOperator(
        task_id="quality_gate_provinces",
        bash_command=gate_command("provinces"),
    )

    crawl_candidates = BashOperator(
        task_id="crawl_candidate_places",
        bash_command=module_command(
            "script.crawl_data.crawl_reference.crawl_candidate_places_raw"
        ),
    )

    gate_candidates = BashOperator(
        task_id="quality_gate_candidates",
        bash_command=gate_command("candidates"),
    )

    validate_places = BashOperator(
        task_id="validate_places_spatially",
        bash_command=module_command(
            "script.crawl_data.crawl_reference.validate_places"
        ),
    )

    gate_validated = BashOperator(
        task_id="quality_gate_validated_places",
        bash_command=gate_command("validated"),
    )

    classify_places = BashOperator(
        task_id="classify_places",
        bash_command=module_command(
            "script.crawl_data.crawl_reference.classify_places"
        ),
    )

    gate_places = BashOperator(
        task_id="quality_gate_places",
        bash_command=gate_command("places"),
    )

    backfill_historical = BashOperator(
        task_id="backfill_historical",
        bash_command=module_command(
            "script.crawl_data.crawl_reference.backfill_historical"
        ),
    )

    (
        crawl_provinces
        >> gate_provinces
        >> crawl_candidates
        >> gate_candidates
        >> validate_places
        >> gate_validated
        >> classify_places
        >> gate_places
        >> backfill_historical
    )