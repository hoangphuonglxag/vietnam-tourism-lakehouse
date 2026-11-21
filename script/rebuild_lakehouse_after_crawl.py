#!/usr/bin/env python3
"""
Pipeline Rebuild Tự Động Toàn Bộ Lakehouse sau khi Crawl:
Bronze -> Silver dbt -> Silver Iceberg -> Gold dbt -> Gold Iceberg -> Export Parquet Power BI
"""
import subprocess
import sys
import time

def run_step(desc: str, cmd: list[str]) -> None:
    print(f"\n{'='*60}")
    print(f"[*] BẮT ĐẦU: {desc}")
    print(f"[*] LỆNH: {' '.join(cmd)}")
    print(f"{'='*60}")
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=False)
    elapsed = time.time() - t0
    if res.returncode != 0:
        print(f"[!] LỖI tại bước: {desc} (Thoát mã: {res.returncode})")
        sys.exit(res.returncode)
    print(f"[+] HOÀN THÀNH: {desc} (Thời gian: {elapsed:.2f}s)")

def main():
    print("\n============================================================")
    print("   TOURISM LAKEHOUSE AUTOMATED REBUILD PIPELINE")
    print("============================================================")
    
    # 1. dbt Silver Layer
    run_step(
        "Build Silver Layer (dbt)",
        ["dbt", "build", "--profiles-dir", "/opt/airflow/project/tourism_dbt", "--project-dir", "/opt/airflow/project/tourism_dbt", "--select", "+tag:silver"]
    )

    # 2. Sync Silver Iceberg
    run_step(
        "Sync Silver Layer to Iceberg",
        ["python3", "/opt/airflow/project/iceberg/writer.py", "--layer", "silver"]
    )

    # 3. dbt Gold Layer
    run_step(
        "Build Gold Layer (dbt)",
        ["dbt", "build", "--profiles-dir", "/opt/airflow/project/tourism_dbt", "--project-dir", "/opt/airflow/project/tourism_dbt", "--select", "tag:gold"]
    )

    # 4. Sync Gold Iceberg
    run_step(
        "Sync Gold Layer to Iceberg",
        ["python3", "/opt/airflow/project/iceberg/writer.py", "--layer", "gold"]
    )

    # 5. Export Parquet for Power BI
    run_step(
        "Export Gold tables to Parquet for Power BI",
        ["python3", "/opt/airflow/project/script/export_gold_to_parquet.py"]
    )

    print("\n============================================================")
    print("   TẤT CẢ CÁC TẦNG LAKEHOUSE ĐÃ ĐƯỢC TÁI TẠO THÀNH CÔNG!")
    print("   POWER BI DATASET ĐÃ ĐƯỢC CẬP NHẬT MỚI NHẤT.")
    print("============================================================\n")

if __name__ == "__main__":
    main()
