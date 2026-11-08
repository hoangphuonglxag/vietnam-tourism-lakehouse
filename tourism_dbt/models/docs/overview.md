{% docs __overview__ %}

# Vietnam Tourism Lakehouse — dbt project

Project dbt này điều phối luồng **Bronze → Staging → Silver** cho dữ liệu du lịch Việt Nam,
chạy trên **DuckDB** và đọc trực tiếp Bronze (JSONL) trên **MinIO** qua `httpfs`.

## Kiến trúc

```
Bronze (MinIO, JSONL, crawl_date=YYYY-MM-DD)
  ├── reference/provinces        ─► stg_provinces            ─► silver_provinces (dimension)
  ├── reference/taxonomy         ─► stg_taxonomy             ─► silver_taxonomy (dimension)
  ├── places                     ─► stg_places               ─► silver_places (dimension)
  ├── reference/place_categories ─► stg_place_categories     ─► silver_place_categories (bridge)
  ├── google_maps/reviews        ─► stg_google_maps_reviews  ─► silver_travel_reviews
  ├── google_maps/ratings        ─► stg_google_maps_ratings  ─► silver_google_maps_rating_snapshots
  ├── youtube/videos             ─► stg_youtube_videos       ─► silver_youtube_videos
  └── youtube/comments           ─► stg_youtube_comments     ─► silver_youtube_comments
                                                                  │
                     tất cả bảng Silver ─────────────────────────► silver_place_temporal_coverage
```

## Nguyên tắc từng lớp

| Lớp | Materialization | Nhiệm vụ |
|---|---|---|
| Staging (`models/staging`) | view | 1 model / 1 dataset Bronze. Đổi tên cột, ép kiểu an toàn (`TRY_CAST`), chuẩn hóa NULL / text / timestamp UTC / `province_id`. **Không** lọc, **không** dedup, **không** join. |
| Silver (`models/silver_layer`) | table | Lọc dữ liệu thiếu khóa, khử trùng lặp theo khóa nghiệp vụ, kiểm tra miền giá trị (giá trị không hợp lệ → NULL), chuẩn hóa `place_id` / `province_id` theo dimension `silver_places`, tính Temporal Coverage Metadata. |

## Xử lý dữ liệu ở lớp Silver

1. **Chuẩn hóa kiểu dữ liệu** — macro `to_int`, `to_double`, `to_bool`, `to_utc_timestamp`.
2. **Chuẩn hóa `place_id`** — TRIM, rỗng → NULL; đối chiếu với `silver_places` (cờ `is_place_in_dim`, test `relationships`).
3. **Chuẩn hóa `province_id`** — macro `normalize_province_id` (`'1'` → `'01'`), ưu tiên giá trị trong dimension.
4. **Chuẩn hóa timestamp** — mọi cột `*_utc` là `TIMESTAMP` UTC; ngày tương đối của Google Maps được ước lượng bằng `normalize_relative_date` kèm cột độ chính xác.
5. **Dữ liệu thiếu** — bản ghi thiếu khóa nghiệp vụ bị loại; chuỗi rỗng / `nan` → NULL.
6. **Dữ liệu trùng lặp** — macro `deduplicate_by_key` (giữ lần crawl mới nhất).
7. **Trường không hợp lệ** — rating ngoài 1–5, count âm, thời điểm ở tương lai → NULL.
8. **Temporal Coverage Metadata** — `silver_place_temporal_coverage`.

## Quy tắc kiểm tra chất lượng

| Quy tắc | Cách triển khai |
|---|---|
| not-null | test `not_null` trên khóa và cột bắt buộc |
| unique | `unique`, `unique_combination_of_columns` theo grain từng bảng |
| accepted values | `accepted_values`, `accepted_range` |
| coverage | `row_count_ratio`, singular test `raw_to_silver_google_maps_coverage`, `monthly_review_coverage` |
| số dòng trước / sau join | `equal_row_count`, singular test `assert_coverage_counts_match_silver_facts` |

## Lệnh thường dùng

```bash
dbt build --select tag:silver+        # chạy + test toàn bộ Silver
dbt test  --select silver_layer       # chỉ test Silver
dbt docs generate && dbt docs serve   # xem tài liệu
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

