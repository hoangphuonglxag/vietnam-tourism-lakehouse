{% docs stg_google_maps_reviews %}
**Staging review Google Maps** — 1 dòng cho mỗi quan sát Bronze (một review crawl lại nhiều lần sẽ có nhiều dòng).

Các bước xử lý:
1. Đọc `source('bronze', 'google_maps_reviews')` (JSONL, `union_by_name` để chịu được khác biệt schema giữa các file).
2. `review_id`, `place_id`: TRIM, chuỗi rỗng / `nan` → NULL (`clean_null`).
3. `rating`, `likes_count`: `TRY_CAST` sang BIGINT (`to_int`); sai định dạng → NULL.
4. `review_text`: bỏ thẻ `<br>`, gộp khoảng trắng (`clean_text`).
5. `review_date` → `review_date_raw` (lowercase, giữ nguyên dạng tương đối để Silver parse).
6. `crawled_at_utc`: chuẩn hóa về TIMESTAMP UTC (`to_utc_timestamp`).
7. Giữ metadata Bronze (`bronze_*`) để truy vết lineage và lọc `record_status` ở Silver.
{% enddocs %}


{% docs stg_youtube_comments %}
**Staging comment YouTube** — 1 dòng cho mỗi quan sát Bronze.

Các bước xử lý:
1. Đọc `source('bronze', 'youtube_comments')`.
2. Đổi tên `text` → `comment_text` và làm sạch (`clean_text`).
3. `likes` → BIGINT; `is_reply` ("True"/"False" của pandas) → BOOLEAN (`to_bool`).
4. `province_id` chuẩn hóa 2 ký tự (`normalize_province_id`), giữ `province_id_raw` để đối soát.
5. `comment_created_at` giữ nguyên chuỗi (`comment_created_at_raw`) vì có thể là ISO timestamp hoặc
   chuỗi tương đối; dữ liệu historical để rỗng.
6. `crawled_at_utc` → TIMESTAMP UTC (bản ghi historical không có offset được coi là UTC).
{% enddocs %}


{% docs stg_youtube_videos %}
**Staging video YouTube** — 1 dòng cho mỗi quan sát Bronze.

Các bước xử lý:
1. Đọc `source('bronze', 'youtube_videos')`.
2. Đổi tên theo chuẩn Silver: `title` → `video_title`, `url` → `video_url`, `thumbnail` → `thumbnail_url`,
   `query` → `search_query`, `crawled_at` → `crawled_at_utc`.
3. `views`, `duration_seconds` → BIGINT.
4. `published_at` mang offset múi giờ nguồn (vd `-07:00`) → quy đổi về UTC (`published_at_utc`),
   đồng thời giữ chuỗi gốc `published_at_raw` theo data contract.
5. `province_id` chuẩn hóa 2 ký tự.
{% enddocs %}


{% docs stg_google_maps_ratings %}
**Staging snapshot rating Google Maps** — 1 dòng cho mỗi lần crawl rating của một địa điểm.

Các bước xử lý:
1. Đọc `source('bronze', 'google_maps_ratings')`.
2. `google_rating` → DOUBLE; `google_review_count`, `rating_1..5_count` → BIGINT.
3. `crawl_status` chuẩn hóa chữ hoa (dữ liệu cũ dùng `success`).
4. `crawled_at` → `crawled_at_utc` (tên chuẩn Silver theo data contract).
5. `province_id` chuẩn hóa 2 ký tự.
{% enddocs %}


{% docs stg_places %}
**Staging dimension địa điểm** — 1 dòng cho mỗi bản ghi place trong mỗi snapshot Bronze.

Các bước xử lý:
1. Đọc file thô bằng `read_text` vì JSONL do pandas ghi có thể chứa token `NaN` (không hợp lệ JSON).
2. Tách nội dung thành từng dòng, thay `NaN` / `Infinity` bằng `null`, rồi `CAST(... AS JSON)`.
3. Trích từng trường bằng `json_extract_string`, ép kiểu tọa độ (DOUBLE), `crawl_eligible` (BOOLEAN).
4. Chuẩn hóa `province_id`, `current_province_id`, `legacy_province_id` về 2 ký tự.
5. Đổi tên các tag OSM (`tourism`, `natural`...) thành `osm_*_tag` để tránh trùng từ khóa SQL.
6. `bronze_crawl_date` lấy từ phân vùng `crawl_date=` trong đường dẫn file.
{% enddocs %}


{% docs stg_provinces %}
**Staging dimension tỉnh/thành phố** — 1 dòng cho mỗi bản ghi province trong mỗi snapshot Bronze (`reference/provinces`).

Các bước xử lý:
1. Đọc `source('bronze', 'provinces')`.
2. Chuẩn hóa `province_id` thành chuỗi 2 ký tự (`normalize_province_id`), giữ `province_id_raw` để đối soát.
3. Ép kiểu 4 tọa độ khung bao (`min_lon`, `min_lat`, `max_lon`, `max_lat`) sang `DOUBLE` (`to_double`).
4. Chuẩn hóa `admin_scope` (lowercase) và `fetched_at_utc` (`TIMESTAMP` UTC).
5. Giữ metadata Bronze (`bronze_*`) để khử trùng lặp theo snapshot mới nhất ở lớp Silver.
{% enddocs %}


{% docs stg_taxonomy %}
**Staging từ điển loại hình du lịch** — 1 dòng cho mỗi bản ghi taxonomy trong mỗi snapshot Bronze (`reference/taxonomy`).

Các bước xử lý:
1. Đọc `source('bronze', 'taxonomy')`.
2. Chuẩn hóa `category_id` chữ in hoa (`CAT001`..`CAT020`).
3. Đổi tên cột `group` → `category_group` (tránh trùng từ khóa SQL `GROUP`), `category` → `category_name`, `subcategory` → `subcategory_name` (lowercase).
4. Giữ `name_vi`, `name_en` và metadata Bronze (`bronze_*`).
{% enddocs %}


{% docs stg_place_categories %}
**Staging bảng ánh xạ địa điểm ↔ loại hình du lịch** — 1 dòng cho mỗi bản ghi trong mỗi snapshot Bronze (`reference/place_categories`).

Các bước xử lý:
1. Đọc `source('bronze', 'place_categories')`.
2. Làm sạch `place_id` và chuẩn hóa `category_id` chữ in hoa.
3. Đổi tên `group` → `category_group`, `category` → `category_name`, `subcategory` → `subcategory_name`.
4. Ép kiểu `is_primary` sang `BOOLEAN` (`to_bool`), chuẩn hóa `classification_method` và `classification_confidence` (lowercase).
5. Giữ metadata Bronze (`bronze_*`).
{% enddocs %}

