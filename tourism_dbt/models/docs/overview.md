{% docs __overview__ %}

# Vietnam Tourism Lakehouse — dbt project

Project dbt này điều phối luồng **Bronze → Staging → Silver → Gold** cho dữ liệu du lịch Việt Nam,
chạy trên **DuckDB**, đọc trực tiếp Bronze (JSONL) trên **MinIO** qua `httpfs`, và đồng bộ cả lớp **Silver** lẫn **Gold** lên **Apache Iceberg** (Lakekeeper REST Catalog + MinIO).

## Kiến trúc

```
Bronze (MinIO, JSONL, crawl_date=YYYY-MM-DD)
  ├── reference/provinces        ─► stg_provinces            ─► silver_provinces (dimension)
  ├── reference/taxonomy         ─► stg_taxonomy             ─► silver_taxonomy (dimension)
  ├── places                     ─► stg_places               ─► silver_places (dimension)
  ├── reference/place_categories ─► stg_place_categories     ─► silver_place_categories (bridge)
  ├── google_maps/reviews        ─► stg_google_maps_reviews  ─► silver_travel_reviews
  ├── google_maps/ratings        ─► stg_google_maps_ratings  ─► silver_google_maps_rating_snapshots
  ├── youtube/videos             ─► stg_youtube_videos       ─┬► silver_youtube_videos
  │                                                           └► silver_youtube_video_snapshots
  └── youtube/comments           ─► stg_youtube_comments     ─► silver_youtube_comments
                                                                  │
                     tất cả bảng Silver ─────────────────────────► silver_place_temporal_coverage
                                                                  │
Gold (3 Data Marts — 6 Bảng Phân tích OLAP / BI) ◄────────────────┘
  ├── Mart 1 (mart_growth_and_trends)
  │     ├── gold_fct_place_monthly_growth
  │     └── gold_fct_place_snapshot_trajectory
  ├── Mart 2 (mart_place_reputation_and_viral)
  │     ├── gold_obt_place_360_profile
  │     └── gold_fct_youtube_video_performance
  └── Mart 3 (mart_regional_and_category)
        ├── gold_fct_province_tourism_summary
        └── gold_fct_category_tourism_summary
```

## Nguyên tắc từng lớp

| Lớp | Materialization | Nhiệm vụ |
|---|---|---|
| Staging (`models/staging`) | view | 1 model / 1 dataset Bronze. Đổi tên cột, ép kiểu an toàn (`TRY_CAST`), chuẩn hóa NULL / text / timestamp UTC / `province_id`. **Không** lọc, **không** dedup, **không** join. |
| Silver (`models/silver_layer`) | table | Lọc dữ liệu thiếu khóa, khử trùng lặp theo khóa nghiệp vụ, kiểm tra miền giá trị (giá trị không hợp lệ → NULL), chuẩn hóa `place_id` / `province_id` theo dimension `silver_places`, tính biến động chuỗi thời gian (`LAG`) và Temporal Coverage Metadata. |
| Gold (`models/gold_layer`) | table | Xây dựng 3 Data Marts (6 bảng Fact/OBT) phục vụ trực tiếp phân tích tăng trưởng lượt xem, biến động rating, hồ sơ 360° phân cụm xu hướng địa điểm, và thống kê theo Tỉnh/Thành phố & Loại hình du lịch. |

## Quy tắc kiểm tra chất lượng

| Quy tắc | Cách triển khai |
|---|---|
| not-null | test `not_null` trên khóa và cột bắt buộc |
| unique | `unique`, `unique_combination_of_columns` theo grain từng bảng |
| accepted values | `accepted_values`, `accepted_range`, `not_negative` |
| coverage | `row_count_ratio`, singular test `raw_to_silver_google_maps_coverage`, `monthly_review_coverage` |
| số dòng trước / sau join | `equal_row_count`, singular test `assert_coverage_counts_match_silver_facts`, `assert_gold_metrics_reconcile_with_silver` |

## Lệnh thường dùng

```bash
dbt build --select +tag:silver        # chạy + test toàn bộ Staging & Silver
dbt build --select tag:gold           # chạy + test toàn bộ Gold Data Marts
dbt docs generate && dbt docs serve   # xem tài liệu & Lineage Graph
```

{% enddocs %}


{% docs source_bronze %}
Lớp **Bronze** của lakehouse: JSONL bất biến (append-only) trên MinIO, phân vùng theo
`crawl_date=YYYY-MM-DD` (ngày UTC của sự kiện crawl). Bronze giữ nguyên giá trị và tên trường
của nguồn (hầu hết là chuỗi), kèm metadata ingestion: `run_id`, `source`, `source_id`,
`source_url`, `ingested_at_utc`, `pipeline_version`, `crawler_version`, `attempt`, `record_status`.
Bản ghi không qua quality gate được ghi vào `quarantine/` và không được đọc ở đây.
Đường dẫn gốc cấu hình bằng var `bronze_root` (mặc định env `TLCN_BRONZE_S3_URI`).
{% enddocs %}
