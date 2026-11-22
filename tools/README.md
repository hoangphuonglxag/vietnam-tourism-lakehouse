# Operational & Maintenance Tools

Thư mục chứa các script hỗ trợ vận hành (DevOps / DataOps) cho hệ thống Vietnam Tourism Data Lakehouse:

| Tên script | Vai trò | Hướng dẫn sử dụng |
| :--- | :--- | :--- |
| `rebuild_lakehouse_after_crawl.py` | Tái tạo tự động toàn bộ Lakehouse từ Silver dbt -> Iceberg -> Gold dbt -> Iceberg -> Parquet Export | `python tools/rebuild_lakehouse_after_crawl.py` |
| `export_gold_to_parquet.py` | Xuất 6 bảng tầng Gold từ DuckDB ra file `.parquet` trong `data/gold_export/` phục vụ dự phòng offline | `python tools/export_gold_to_parquet.py` |
| `trigger_crawl.py` | Tiện ích dòng lệnh (CLI) để kích hoạt nhanh Airflow DAG cào dữ liệu từ bên ngoài | `python tools/trigger_crawl.py` |
