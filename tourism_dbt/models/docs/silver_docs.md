{% docs silver_provinces %}
**Dimension tỉnh/thành phố (Silver)** — grain: **1 dòng / `province_id`**.

| Bước | Xử lý | Nhóm quy tắc |
|---|---|---|
| 1 | Loại bản ghi thiếu `province_id` / `province_name` hoặc `record_status <> 'success'` | Dữ liệu thiếu |
| 2 | Tính `first_seen_crawl_date`, `last_seen_crawl_date`, `snapshot_count` qua các snapshot | Truy vết |
| 3 | Khử trùng lặp theo `province_id`, giữ bản ghi ở snapshot mới nhất (`deduplicate_by_key`) | Trùng lặp |
| 4 | Kiểm tra miền tọa độ khung bao (`min_lon <= max_lon` trong `[-180, 180]`, `min_lat <= max_lat` trong `[-90, 90]`); tính tâm khung bao (`center_lat`, `center_lon`) | Không hợp lệ |
{% enddocs %}


{% docs silver_taxonomy %}
**Dimension từ điển phân loại loại hình du lịch (Silver)** — grain: **1 dòng / `category_id`**.

| Bước | Xử lý | Nhóm quy tắc |
|---|---|---|
| 1 | Loại bản ghi thiếu `category_id`, `category_group`, `category_name` hoặc `record_status <> 'success'` (theo data contract mục 4.2) | Dữ liệu thiếu |
| 2 | Tính `first_seen_crawl_date`, `last_seen_crawl_date`, `snapshot_count` | Truy vết |
| 3 | Khử trùng lặp theo `category_id`, giữ bản ghi của snapshot mới nhất | Trùng lặp |
{% enddocs %}


{% docs silver_place_categories %}
**Bridge table địa điểm ↔ loại hình du lịch (Silver)** — grain: **1 dòng / (`place_id`, `category_id`)**.

| Bước | Xử lý | Nhóm quy tắc |
|---|---|---|
| 1 | Loại bản ghi thiếu `place_id` / `category_id` hoặc `record_status <> 'success'` | Dữ liệu thiếu |
| 2 | Khử trùng lặp theo (`place_id`, `category_id`), giữ bản ghi từ snapshot mới nhất (ưu tiên `is_primary = true`) | Trùng lặp |
| 3 | Chuẩn hóa `is_primary` (`NULL` → `FALSE`) và kiểm tra `classification_confidence` trong `('high', 'medium', 'low')` | Không hợp lệ |
| 4 | `LEFT JOIN` `silver_taxonomy` (lấy tên hiển thị `category_name_vi`, `category_name_en`, nhóm chuẩn) và `LEFT JOIN` `silver_places` (lấy `place_name`, `province_id`, `province_name`) | Chuẩn hóa tham chiếu |
{% enddocs %}


{% docs silver_places %}
**Dimension địa điểm (Silver)** — grain: **1 dòng / `place_id`**. Đây là nguồn chuẩn của
`place_id` / `province_id` dùng để chuẩn hóa mọi bảng fact và làm spine cho Temporal Coverage.

| Bước | Xử lý | Nhóm quy tắc |
|---|---|---|
| 1 | Loại bản ghi thiếu `place_id` / `place_name` hoặc `record_status <> 'success'` | Dữ liệu thiếu |
| 2 | Tính `first_seen_crawl_date`, `last_seen_crawl_date`, `snapshot_count` qua các snapshot | Truy vết |
| 3 | Khử trùng lặp theo `place_id`, giữ bản ghi của snapshot mới nhất (`deduplicate_by_key`) | Trùng lặp |
| 4 | Tọa độ ngoài miền [-90, 90] / [-180, 180] → NULL; `crawl_eligible` NULL → FALSE | Không hợp lệ |
| 5 | `is_in_latest_snapshot` = place có mặt trong snapshot mới nhất | Theo dõi |

> Place không còn xuất hiện ở snapshot mới vẫn được giữ lại (`is_in_latest_snapshot = false`)
> để các review/video cũ vẫn join được.
{% enddocs %}


{% docs silver_travel_reviews %}
**Review Google Maps (Silver)** — grain: **1 dòng / `review_id`**.

| Bước | Xử lý | Nhóm quy tắc |
|---|---|---|
| 1 | Loại bản ghi thiếu `review_id` / `place_id` / `crawled_at_utc` hoặc bị quarantine | Dữ liệu thiếu |
| 2 | Parse `review_date_raw` (vd "một tháng trước") thành ngày ước lượng = ngày crawl − khoảng thời gian (`normalize_relative_date`), kèm `review_date_precision` (day/week/month/year/unknown) | Timestamp |
| 3 | Đếm `observation_count` (số lần review được crawl) và `first_crawled_at_utc` | Truy vết |
| 4 | Khử trùng lặp theo `review_id`: thuộc tính thay đổi được (`likes_count`, `review_text`) lấy từ **lần crawl mới nhất** | Trùng lặp |
| 5 | `review_date` lấy từ quan sát có **độ chính xác cao nhất** (day > week > month > year), cùng độ chính xác thì lấy lần crawl sớm nhất — vì cùng một review, lần crawl càng sau thì chuỗi tương đối càng thô | Timestamp |
| 6 | `rating` ngoài 1–5 → NULL; `likes_count` âm → NULL | Không hợp lệ |
| 7 | LEFT JOIN `silver_places` để lấy `place_name`, `province_id`, `province_name` chuẩn; `is_place_in_dim` đánh dấu place không có trong dimension. Join không làm thay đổi số dòng (test `equal_row_count`) | Chuẩn hóa place/province, số dòng trước/sau join |

> **Lưu ý:** ngày tham chiếu là ngày crawl theo UTC; với precision `year` sai số có thể tới ±6 tháng,
> vì vậy các phân tích theo tháng chỉ nên dùng precision `day` / `week` / `month`.
{% enddocs %}


{% docs silver_youtube_comments %}
**Comment YouTube (Silver)** — grain: **1 dòng / (`place_id`, `comment_key`)**.
Một video có thể gắn với nhiều place nên cùng một comment có thể xuất hiện ở nhiều place.

| Bước | Xử lý | Nhóm quy tắc |
|---|---|---|
| 1 | Loại bản ghi thiếu `place_id` / `video_id` / `crawled_at_utc`, bản ghi không có cả `comment_id` lẫn nội dung, bản ghi quarantine | Dữ liệu thiếu |
| 1b | `comment_key` = `comment_id` nếu có; ngược lại (dữ liệu historical) = `'sk_' || md5(video_id || author || comment_text)` — `is_surrogate_comment_key` đánh dấu trường hợp này | Khóa |
| 2 | Đếm `observation_count`, `first_crawled_at_utc` | Truy vết |
| 3 | Khử trùng lặp theo (`place_id`, `comment_key`), giữ lần crawl mới nhất | Trùng lặp |
| 4 | `comment_created_at_utc`: chuỗi ISO → `exact`; chuỗi tương đối ("2 năm trước", "3 weeks ago") → ước lượng theo ngày crawl; không parse được → NULL / `unknown` | Timestamp |
| 5 | `likes` âm → NULL; thời điểm tạo sau thời điểm crawl > 1 ngày → NULL; `is_reply` NULL → FALSE | Không hợp lệ |
| 6 | LEFT JOIN `silver_places`, ưu tiên `place_name` / `province_id` của dimension | Chuẩn hóa place/province |
{% enddocs %}


{% docs silver_youtube_videos %}
**Video YouTube (Silver)** — grain: **1 dòng / (`place_id`, `video_id`)**.

| Bước | Xử lý | Nhóm quy tắc |
|---|---|---|
| 1 | Loại bản ghi thiếu `place_id` / `video_id` / `crawled_at_utc` hoặc quarantine | Dữ liệu thiếu |
| 2 | Đếm `observation_count`, `first_crawled_at_utc` | Truy vết |
| 3 | Khử trùng lặp theo (`place_id`, `video_id`), giữ lần crawl mới nhất (lượt xem mới nhất) | Trùng lặp |
| 4 | `views` / `duration_seconds` âm → NULL; `published_at_utc` sau thời điểm crawl > 1 ngày → NULL | Không hợp lệ |
| 5 | Tính `published_date`, `published_month` cho phân tích theo thời gian | Timestamp |
| 6 | LEFT JOIN `silver_places` để chuẩn hóa place/province | Chuẩn hóa place/province |
{% enddocs %}


{% docs silver_google_maps_rating_snapshots %}
**Snapshot rating Google Maps (Silver)** — grain: **1 dòng / (`place_id`, `snapshot_date`)**.
Đây là chuỗi thời gian rating theo ngày của mỗi địa điểm.

| Bước | Xử lý | Nhóm quy tắc |
|---|---|---|
| 1 | Chỉ giữ lần crawl `crawl_status = 'SUCCESS'`; các lần lỗi là dữ liệu vận hành (data contract mục 6) | Dữ liệu thiếu |
| 2 | `snapshot_date` = ngày UTC của `crawled_at_utc` | Timestamp |
| 3 | Nhiều lần crawl trong 1 ngày → giữ lần mới nhất | Trùng lặp |
| 4 | `google_rating` ngoài 0–5 → NULL; các count âm → NULL | Không hợp lệ |
| 5 | `rating_distribution_total`, `has_rating_distribution` (phân phối bằng 0 nghĩa là nguồn không cung cấp, không phải NULL), `has_rating_value` | Bổ sung |
| 6 | LEFT JOIN `silver_places` để chuẩn hóa place/province | Chuẩn hóa place/province |
{% enddocs %}


{% docs silver_place_temporal_coverage %}
**Temporal Coverage Metadata** — grain: **1 dòng / `place_id` trong `silver_places`**.

Sau ingestion, bảng này đánh giá độ phủ theo thời gian của từng place để xác định place nào:
có đủ temporal history, sparse, chỉ có recent data, hoặc phù hợp cho forecasting.
**Không yêu cầu tất cả ~7,000 places đều phải đủ điều kiện forecasting.**

### Các bước xử lý
1. **as_of_date** — lấy từ var `coverage_as_of_date`; nếu NULL thì dùng ngày crawl lớn nhất trong các bảng Silver
   (giúp kết quả tái lập được, không phụ thuộc ngày chạy).
2. **Thống kê theo nguồn** (mỗi CTE 1 dòng / place):
   - reviews: `review_count`, `review_min_date`, `review_max_date`, `review_active_month_count`
   - videos: `video_count`, `video_min_published_date`, `video_max_published_date`, `video_active_month_count`
   - comments: `comment_count`, `comment_min_date`, `comment_max_date`, `comment_active_month_count`
   - ratings: `rating_snapshot_count`, `rating_min_snapshot_date`, `rating_max_snapshot_date`
3. **Tháng hoạt động** — hợp nhất (UNION) các tháng có review/video/comment. Chỉ tính ngày có precision
   `exact` / `day` / `week` / `month`; ngày precision `year` quá thô nên không được tính là tháng hoạt động
   (nhưng vẫn được dùng cho min/max date).
4. **Join vào spine** `silver_places` bằng LEFT JOIN; place không có dữ liệu có count = 0.
   Số dòng phải bằng `silver_places` (test `equal_row_count`).
5. **Phân loại** (ngưỡng cấu hình trong `dbt_project.yml`):

| Cờ | Điều kiện |
|---|---|
| `has_temporal_history` | `history_span_months >= coverage_min_history_months` (12) **và** `total_active_month_count >= coverage_min_active_months` (6) |
| `has_recent_data` | `days_since_last_activity <= coverage_recent_window_days` (90) |
| `is_sparse` | có dữ liệu nhưng `total_active_month_count <= coverage_sparse_max_active_months` (2) |
| `has_rating_history` | `rating_snapshot_count >= coverage_min_rating_snapshots` (2) |

`coverage_status` (xét theo thứ tự):

| Giá trị | Ý nghĩa |
|---|---|
| `no_data` | không có review / video / comment nào |
| `forecast_ready` | đủ temporal history **và** có recent data → ứng viên forecasting (`is_forecast_eligible = true`) |
| `sparse` | dữ liệu rải rác, quá ít tháng hoạt động |
| `recent_only` | chỉ có dữ liệu gần đây, chưa đủ lịch sử |
| `stale_history` | đủ lịch sử nhưng không có dữ liệu gần đây |
| `partial` | các trường hợp còn lại |
{% enddocs %}

