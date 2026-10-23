from datetime import datetime
import sys

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

PROJECT_DIR = "/opt/airflow/project"
sys.path.insert(0, PROJECT_DIR)

from script.alerts.discord import dag_success, task_failure
from script.crawl_data.utils.crawl_plan import build_crawl_plan

from airflow.models.param import Param

PYTHON_ENV = f"export PYTHONPATH={PROJECT_DIR}:${{PYTHONPATH:-}}"


def job_command(module: str, exports: tuple[str, ...] = ()) -> str:
    lines = [
        "set -euo pipefail",
        f"cd {PROJECT_DIR}",
        PYTHON_ENV,
        *exports,
        f"python -m {module}",
    ]
    return "\n".join(lines)


def build_plan_task(**context: object) -> str:
    dag_run = context.get("dag_run")
    request = getattr(dag_run, "conf", None) or {}
    run_id = str(getattr(dag_run, "run_id", "manual"))

    plan_path = build_crawl_plan(dict(request), run_id=run_id)

    if not plan_path.is_file():
        raise FileNotFoundError(
            f"Crawl planner did not create its output: {plan_path}"
        )

    return str(plan_path)


PLAN_EXPORT = (
    'plan_path="{{ ti.xcom_pull(task_ids=\'build_crawl_plan\') or \'\' }}"',
    'if [ -z "$plan_path" ] || [ "$plan_path" = "None" ]; then',
    '  echo "ERROR: build_crawl_plan returned no plan path" >&2',
    "  exit 1",
    "fi",
    'if [ ! -f "$plan_path" ]; then',
    '  echo "ERROR: crawl plan does not exist: $plan_path" >&2',
    "  exit 1",
    "fi",
    'export TLCN_CRAWL_PLAN_PATH="$plan_path"',
)


with DAG(
    dag_id="dag_crawl_social_historical_data",
    description="Plan and selectively refresh scoped Google Maps and YouTube datasets",
    start_date=datetime(2026, 1, 1),
    schedule="0 3 * * 1",
    catchup=False,
    max_active_runs=1,
    tags=["tourism", "social", "bronze"],
    on_failure_callback=task_failure,
    on_success_callback=dag_success,
    default_args={"on_failure_callback": task_failure},
    params={
        "place_ids": Param(
            ["OSM_node_4346215389"],
            type="array",
            items={"type": "string"},
            description="Danh sách place_id cần crawl",
        ),
        "datasets": Param(
            ["google_reviews"],
            type="array",
            items={
                "type": "string",
                "enum": [
                    "google_ratings",
                    "google_reviews",
                    "youtube_videos",
                    "youtube_comments",
                ],
            },
            description="Các dataset cần chạy",
        ),
        "dry_run": Param(
            True,
            type="boolean",
            description="True chỉ lập kế hoạch, False cho phép crawl",
        ),
        "force_refresh": Param(
            False,
            type="boolean",
            description="Bỏ qua freshness khi lập kế hoạch",
        ),
        "freshness_days": Param(
            {
                "google_ratings": 7,
                "google_reviews": 14,
                "youtube_videos": 7,
                "youtube_comments": 7,
            },
            type="object",
            description="Ngưỡng freshness theo dataset",
        ),
    },
) as dag:

    plan = PythonOperator(
        task_id="build_crawl_plan",
        python_callable=build_plan_task,
    )

    google_ratings = BashOperator(
        task_id="crawl_google_maps_ratings",
        bash_command=job_command(
            "script.crawl_data.jobs_crawl_social.job_google_maps_ratings",
            (
                "export HEADLESS=true",
                *PLAN_EXPORT,
                "export GOOGLE_MAPS_DELAY_SECONDS=${GOOGLE_MAPS_DELAY_SECONDS:-1.0}",
            ),
        ),
    )

    google_reviews = BashOperator(
        task_id="crawl_google_maps_reviews",
        bash_command=job_command(
            "script.crawl_data.jobs_crawl_social.job_google_maps_reviews",
            (
                "export HEADLESS=true",
                *PLAN_EXPORT,
                "export GOOGLE_MAPS_REVIEWS_DELAY_SECONDS=${GOOGLE_MAPS_REVIEWS_DELAY_SECONDS:-1.0}",
            ),
        ),
    )

    youtube_videos = BashOperator(
        task_id="crawl_youtube_videos",
        bash_command=job_command(
            "script.crawl_data.jobs_crawl_social.job_youtube_videos",
            PLAN_EXPORT,
        ),
    )

    youtube_comments = BashOperator(
        task_id="crawl_youtube_comments",
        bash_command=job_command(
            "script.crawl_data.jobs_crawl_social.job_youtube_comments",
            PLAN_EXPORT,
        ),
    )

    plan >> [google_ratings, google_reviews, youtube_videos]
    youtube_videos >> youtube_comments