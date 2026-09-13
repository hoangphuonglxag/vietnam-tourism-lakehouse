from datetime import datetime
import sys

from airflow import DAG
from airflow.operators.bash import BashOperator

PROJECT_DIR = "/opt/airflow/project"
sys.path.insert(0, PROJECT_DIR)
from script.crawl_data.alerts.discord import dag_success, task_failure


PYTHON_ENV = f"export PYTHONPATH={PROJECT_DIR}:${{PYTHONPATH:-}}"


def module_command(module: str) -> str:
    return f"set -euo pipefail\ncd {PROJECT_DIR}\n{PYTHON_ENV}\npython -m {module}"


def gate_command(stage: str) -> str:
    return module_command(f"script.crawl_data.quality_gate {stage}")


with DAG(
    dag_id="tourism_reference_pipeline",
    description="Infrequent province boundaries and place master refresh",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["tourism", "reference", "places"],
    on_failure_callback=task_failure,
    on_success_callback=dag_success,
    default_args={"on_failure_callback": task_failure},
) as dag:
    crawl_provinces = BashOperator(
        task_id="crawl_provinces",
        bash_command=module_command("script.crawl_data.crawl_province"),
    )
    gate_provinces = BashOperator(
        task_id="quality_gate_provinces",
        bash_command=gate_command("provinces"),
    )
    crawl_candidates = BashOperator(
        task_id="crawl_candidate_places",
        bash_command=module_command("script.crawl_data.crawl_candidate_places_raw"),
    )
    gate_candidates = BashOperator(
        task_id="quality_gate_candidates",
        bash_command=gate_command("candidates"),
    )
    spatial_validate = BashOperator(
        task_id="validate_places_spatially",
        bash_command=module_command("script.crawl_data.validate_places"),
    )
    gate_validated = BashOperator(
        task_id="quality_gate_validated_places",
        bash_command=gate_command("validated"),
    )
    classify = BashOperator(
        task_id="classify_places",
        bash_command=module_command("script.crawl_data.classify_places"),
    )
    gate_places = BashOperator(
        task_id="quality_gate_places",
        bash_command=gate_command("places"),
    )

    crawl_provinces >> gate_provinces >> crawl_candidates >> gate_candidates
    gate_candidates >> spatial_validate >> gate_validated >> classify >> gate_places
