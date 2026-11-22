import json
import subprocess
import sys

def main():
    conf = {
        "datasets": ["google_reviews"],
        "dry_run": False,
        "core_only": True,
        "force_refresh": False,
    }
    cmd = [
        "airflow",
        "dags",
        "trigger",
        "dag_crawl_social_historical_data",
        "--conf",
        json.dumps(conf),
    ]
    print(f"Triggering Real Crawl DAG with conf: {conf}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    print("STDOUT:", res.stdout)
    print("STDERR:", res.stderr)
    sys.exit(res.returncode)

if __name__ == "__main__":
    main()
