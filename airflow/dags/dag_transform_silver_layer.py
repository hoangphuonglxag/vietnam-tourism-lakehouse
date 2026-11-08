from datetime import datetime
import sys

from airflow import DAG
from airflow.operators.bash import BashOperator


PROJECT_DIR = "/opt/airflow/project"
DBT_DIR = f"{PROJECT_DIR}/tourism_dbt"
sys.path.insert(0, PROJECT_DIR)

from script.alerts.discord import dag_success, task_failure


with DAG(
    dag_id="dag_transform_silver_layer",
    description="Bronze -> Staging -> Silver (dbt + DuckDB) -> Apache Iceberg (Lakekeeper + MinIO)",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["tourism", "lakehouse", "silver", "dbt", "iceberg"],
    on_failure_callback=task_failure,
    on_success_callback=dag_success,
    default_args={
        "on_failure_callback": task_failure,
    },
) as dag:

    # TASK 1: dbt build (Staging views + Silver tables + Tests)

    dbt_build_silver = BashOperator(
        task_id="dbt_build_silver",
        bash_command=f"""
        set -euo pipefail

        echo "========================================"
        echo "TASK 1: DBT BUILD SILVER LAYER + TESTS"
        echo "========================================"

        cd {DBT_DIR}

        dbt build --profiles-dir . --log-path /tmp/dbt_logs --target-path /tmp/dbt_target --select +tag:silver

        echo ""
        echo "DBT BUILD SILVER SUCCESS"
        """,
    )

    # TASK 2: DuckDB -> PyArrow -> PyIceberg -> Lakekeeper/MinIO

    write_silver_iceberg = BashOperator(
        task_id="write_silver_iceberg",
        bash_command=f"""
        set -euo pipefail

        echo "========================================"
        echo "TASK 2: WRITE SILVER TABLES TO ICEBERG"
        echo "========================================"

        cd {PROJECT_DIR}

        python3 iceberg/writer.py

        echo ""
        echo "ICEBERG WRITE SUCCESS"
        """,
    )

    # TASK 3: Validate Silver Iceberg tables on MinIO

    validate_silver_iceberg = BashOperator(
        task_id="validate_silver_iceberg",
        bash_command=f"""
        set -euo pipefail

        echo "========================================"
        echo "TASK 3: VALIDATE SILVER ICEBERG TABLES"
        echo "========================================"

        cd {PROJECT_DIR}

        python3 iceberg/check_table.py

        echo ""
        echo "ICEBERG VALIDATION SUCCESS"
        """,
    )

    # Dependency

    dbt_build_silver >> write_silver_iceberg >> validate_silver_iceberg
