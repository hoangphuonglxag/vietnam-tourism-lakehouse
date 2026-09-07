from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator


PROJECT_DIR = "/opt/airflow/project"
DBT_DIR = f"{PROJECT_DIR}/tourism_dbt"


with DAG(
    dag_id="tourism_lakehouse_test",
    description="Test dbt -> DuckDB -> PyIceberg -> Lakekeeper -> MinIO",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["tourism", "lakehouse", "test"],
) as dag:

    # =========================================================
    # TASK 1: dbt -> DuckDB
    # =========================================================

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=f"""
        set -e

        echo "========================================"
        echo "TASK 1: DBT RUN"
        echo "========================================"

        cd {DBT_DIR}

        dbt run --profiles-dir .

        echo ""
        echo "DBT RUN SUCCESS"
        """,
    )

    # =========================================================
    # TASK 2: DuckDB -> PyArrow -> PyIceberg -> Lakekeeper
    # =========================================================

    write_iceberg = BashOperator(
        task_id="write_iceberg",
        bash_command=f"""
        set -e

        echo "========================================"
        echo "TASK 2: WRITE TO ICEBERG"
        echo "========================================"

        cd {PROJECT_DIR}

        python iceberg/writer.py

        echo ""
        echo "ICEBERG WRITE SUCCESS"
        """,
    )

    # =========================================================
    # TASK 3: Validate Iceberg table
    # =========================================================

    validate_iceberg = BashOperator(
        task_id="validate_iceberg",
        bash_command=f"""
        set -e

        echo "========================================"
        echo "TASK 3: VALIDATE ICEBERG"
        echo "========================================"

        cd {PROJECT_DIR}

        python iceberg/check_table.py

        echo ""
        echo "ICEBERG VALIDATION SUCCESS"
        """,
    )

    # =========================================================
    # Dependency
    # =========================================================

    dbt_run >> write_iceberg >> validate_iceberg