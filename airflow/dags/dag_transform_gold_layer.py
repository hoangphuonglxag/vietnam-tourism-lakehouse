from datetime import datetime, timedelta
import sys

from airflow import DAG
from airflow.operators.bash import BashOperator


PROJECT_DIR = "/opt/airflow/project"
DBT_DIR = f"{PROJECT_DIR}/tourism_dbt"
sys.path.insert(0, PROJECT_DIR)

from script.alerts.discord import dag_success, task_failure


with DAG(
    dag_id="dag_transform_gold_layer",
    description="Silver -> Gold Data Marts (dbt + DuckDB) -> Apache Iceberg (Lakekeeper + MinIO)",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["tourism", "lakehouse", "gold", "dbt", "iceberg"],
    on_failure_callback=task_failure,
    on_success_callback=dag_success,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=1),
        "on_failure_callback": task_failure,
    },
) as dag:

    # TASK 1: dbt build (Gold Data Mart tables + Tests)

    dbt_build_gold = BashOperator(
        task_id="dbt_build_gold",
        bash_command=f"""
        set -euo pipefail

        echo "========================================"
        echo "TASK 1: DBT BUILD GOLD LAYER + TESTS"
        echo "========================================"

        cd {DBT_DIR}

        dbt build --profiles-dir . --log-path /tmp/dbt_logs --target-path /tmp/dbt_target --select tag:gold

        echo ""
        echo "DBT BUILD GOLD SUCCESS"
        """,
    )

    # TASK 2: DuckDB -> PyArrow -> PyIceberg -> Lakekeeper/MinIO (Gold Namespace)

    write_gold_iceberg = BashOperator(
        task_id="write_gold_iceberg",
        bash_command=f"""
        set -euo pipefail

        echo "========================================"
        echo "TASK 2: WRITE GOLD TABLES TO ICEBERG"
        echo "========================================"

        cd {PROJECT_DIR}

        python3 iceberg/writer.py --layer gold

        echo ""
        echo "GOLD ICEBERG WRITE SUCCESS"
        """,
    )

    # TASK 3: Validate Gold Iceberg tables on MinIO

    validate_gold_iceberg = BashOperator(
        task_id="validate_gold_iceberg",
        bash_command=f"""
        set -euo pipefail

        echo "========================================"
        echo "TASK 3: VALIDATE GOLD ICEBERG TABLES"
        echo "========================================"

        cd {PROJECT_DIR}

        python3 iceberg/check_table.py --layer gold

        echo ""
        echo "GOLD ICEBERG VALIDATION SUCCESS"
        """,
    )

    # Dependency

    dbt_build_gold >> write_gold_iceberg >> validate_gold_iceberg
