# Vietnam Tourism Lakehouse - Data Dictionary (Từ điển dữ liệu)

**Phiên bản:** 1.0  
**Hệ thống:** Vietnam Tourism Lakehouse  
**Mục đích:** Tài liệu hóa toàn diện cấu trúc dữ liệu, kiểu dữ liệu, ràng buộc và ý nghĩa nghiệp vụ qua từng tầng kiến trúc từ Raw (Bronze) qua Xử lý (Staging, Silver) tới Phục vụ phân tích (Gold / Data Warehouse & Marts).

---

## 1. Tổng quan các tầng dữ liệu (Data Architecture Layers)

```text
[Nguồn: OSM, Google Maps, YouTube]
               │
               ▼
   [BRONZE LAYER (Raw)]          -> Lưu trữ JSONL append-only, giữ nguyên dạng nguồn + metadata
               │
               ▼
   [STAGING LAYER (stg_*)]       -> Chuẩn hóa giao diện nguồn: 1-1 với Bronze, ép kiểu (cast), rename cột
               │
               ▼
   [SILVER LAYER (silver_*)]     -> Logic nghiệp vụ: Khử trùng lặp (dedup), lọc rác, parse relative date
               │
               ▼
   [GOLD LAYER (DW & Marts)]     -> Mô hình chiều (Star Schema: Facts & Dimensions), KPIs & Aggregations
```

---

## 2. Danh mục các Dataset chính

1. **`places` & `reference`**: Dữ liệu chủ (Master Reference) về danh mục địa điểm, ranh giới tỉnh thành từ OpenStreetMap (OSM).
2. **`google_maps_ratings`**: Dữ liệu quan sát tổng thể (rating trung bình, số lượng đánh giá, phân bố số sao 1-5) của từng địa điểm.
3. **`google_maps_reviews`**: Dữ liệu chi tiết từng đánh giá của người dùng (nội dung bình luận, điểm chấm, lượt thích, thời gian).
4. **`youtube_videos`**: Dữ liệu video liên quan đến địa điểm du lịch (tiêu đề, lượt xem, thời lượng, kênh phát hành).
5. **`youtube_comments`**: Dữ liệu bình luận chi tiết dưới các video du lịch.

---

## 3. Chi tiết tầng BRONZE (Raw Storage)

Tất cả bảng Bronze đều lưu dạng JSONL phân vùng theo ngày crawl (`crawl_date=YYYY-MM-DD`) trên MinIO S3 (`s3://lakehouse/bronze/`) kèm các trường Audit Metadata:

| Tên trường metadata | Kiểu dữ liệu | Ý nghĩa |
|---|---|---|
| `run_id` | String | Mã định danh duy nhất của lượt crawl (Airflow run hoặc manual batch). |
| `source` | String | Nguồn dữ liệu (`osm`, `google_maps`, `youtube`). |
| `source_id` | String | ID của bản ghi từ nguồn gốc (ID place, review ID, video ID). |
| `source_url` | String | Đường dẫn URL tương ứng khi crawl. |
| `ingested_at_utc` | Timestamp (UTC) | Thời điểm hệ thống ingest dữ liệu vào Lakehouse. |
| `pipeline_version`| String | Phiên bản mã nguồn pipeline. |
| `crawler_version` | String | Phiên bản crawler tương ứng. |
| `attempt` | Integer | Số lần retry khi crawl. |
| `record_status` | Enum | `success` (hợp lệ) hoặc `quarantine` (bị cô lập do vi phạm schema). |

---

## 4. Chi tiết tầng STAGING (`stg_*`) & SILVER (`silver_*`)

Tầng Staging chuẩn hóa 1-1, tầng Silver thực thi logic làm sạch chuyên sâu.

### 4.1 Bảng `places` (Địa điểm du lịch)

* **Nguồn:** `s3://lakehouse/bronze/places/`
* **Staging:** `stg_places` (ép kiểu tọa độ, rename cột).
* **Silver:** `silver_places` (chỉ giữ `validation_status = 'valid'`, phân loại category rõ ràng, khử trùng lặp).

| Tên cột | Kiểu dữ liệu | Nullable | Mô tả nghiệp vụ & Quy tắc Silver |
|---|---|---|---|
| `place_id` | String | No | Mã định danh duy nhất của địa điểm (Business Key, vd: `OSM_node_12345`). |
| `place_name` | String | No | Tên địa điểm chuẩn hóa (đã trim khoảng trắng). |
| `name_vi` | String | Yes | Tên tiếng Việt (nếu có trên OSM). |
| `name_en` | String | Yes | Tên tiếng Anh. |
| `province_id` | String | No | Mã tỉnh thành chuẩn hóa theo danh mục hành chính Việt Nam. |
| `province_name` | String | No | Tên tỉnh/thành phố (vd: Đà Nẵng, Quảng Nam...). |
| `latitude` | Float64 | No | Vĩ độ (nằm trong khoảng `[8.0, 24.0]` của Việt Nam). |
| `longitude` | Float64 | No | Kinh độ (nằm trong khoảng `[102.0, 110.0]` của Việt Nam). |
| `category` | String | No | Nhóm danh mục du lịch: `attraction`, `hotel`, `restaurant`, `natural`, `historic`, `entertainment`. |
| `osm_type` | String | No | Loại đối tượng OSM (`node`, `way`, `relation`). |
| `osm_id` | String | No | ID gốc từ OpenStreetMap. |
| `is_crawl_eligible`| Boolean | No | Cờ đánh dấu địa điểm có đủ điều kiện đem đi crawl dữ liệu xã hội hay không. |

---

### 4.2 Bảng `google_maps_reviews` (Đánh giá người dùng)

* **Nguồn:** `s3://lakehouse/bronze/google_maps/reviews/`
* **Staging:** `stg_google_maps_reviews` (ép kiểu `rating` sang INT, `likes_count` sang INT, đổi tên `review_date` thành `review_date_raw`).
* **Silver:** `silver_google_maps_reviews` (Khử trùng lặp theo `review_id`, parse `review_date_raw` thành ngày thực tế, lọc text rác).

| Tên cột | Kiểu dữ liệu | Nullable | Mô tả nghiệp vụ & Quy tắc Silver |
|---|---|---|---|
| `review_id` | String | No | Mã định danh duy nhất của bài đánh giá (Khóa chính sau khi dedup). |
| `place_id` | String | No | Khóa ngoại tham chiếu tới `silver_places`. |
| `rating` | Integer | No | Số sao đánh giá từ 1 đến 5 (Silver lọc bỏ các giá trị ngoài dải 1-5). |
| `review_text` | String | Yes | Nội dung đánh giá (đã làm sạch ký tự đặc biệt, trim khoảng trắng). |
| `review_date_raw`| String | Yes | Chuỗi gốc nguồn crawl (vd: "2 tuần trước", "1 tháng trước", "3 days ago"). |
| `review_date` | Date | No | Ngày được quy đổi về định dạng `YYYY-MM-DD` dựa vào `crawled_at_utc - relative_offset`. |
| `review_date_precision` | Enum | No | Độ chính xác quy đổi: `'day'`, `'week'`, `'month'`, `'year'`. |
| `likes_count` | Integer | No | Số lượt thích review (nếu null gán về 0). |
| `crawled_at_utc` | Timestamp | No | Thời điểm crawl đánh giá này. |

---

### 4.3 Bảng `google_maps_ratings` (Tổng quan đánh giá địa điểm)

* **Nguồn:** `s3://lakehouse/bronze/google_maps/ratings/`
* **Silver:** `silver_google_maps_ratings` (Giữ snapshot đánh giá mới nhất hoặc snapshot theo ngày của địa điểm).

| Tên cột | Kiểu dữ liệu | Nullable | Mô tả nghiệp vụ & Quy tắc Silver |
|---|---|---|---|
| `place_id` | String | No | Khóa ngoại tham chiếu `silver_places`. |
| `google_rating` | Float64 | Yes | Điểm đánh giá trung bình tại thời điểm crawl (từ 0.0 đến 5.0). |
| `google_review_count` | Integer | Yes | Tổng số lượng đánh giá công khai trên Google Maps. |
| `rating_5_count` | Integer | No | Số đánh giá 5 sao. |
| `rating_4_count` | Integer | No | Số đánh giá 4 sao. |
| `rating_3_count` | Integer | No | Số đánh giá 3 sao. |
| `rating_2_count` | Integer | No | Số đánh giá 2 sao. |
| `rating_1_count` | Integer | No | Số đánh giá 1 sao. |
| `snapshot_date` | Date | No | Ngày ghi nhận chỉ số đánh giá. |

---

### 4.4 Bảng `youtube_videos` (Video liên quan)

* **Nguồn:** `s3://lakehouse/bronze/youtube/videos/`
* **Silver:** `silver_youtube_videos` (Khử trùng lặp theo `(place_id, video_id)`, lọc các video không liên quan nếu resolution_score thấp).

| Tên cột | Kiểu dữ liệu | Nullable | Mô tả nghiệp vụ & Quy tắc Silver |
|---|---|---|---|
| `video_id` | String | No | Mã video YouTube duy nhất (11 ký tự). |
| `place_id` | String | No | Khóa ngoại tham chiếu `silver_places`. |
| `video_title` | String | No | Tiêu đề video đã chuẩn hóa text. |
| `channel_id` | String | Yes | ID kênh YouTube đăng tải. |
| `channel_name` | String | Yes | Tên kênh YouTube (vd: "Khoai Lang Thang", "VTV Travel"...). |
| `views_count` | Integer | No | Số lượt xem video tại thời điểm crawl (>= 0). |
| `duration_seconds`| Integer | Yes | Thời lượng video tính bằng giây. |
| `published_at` | Timestamp | Yes | Thời điểm video được phát hành lên YouTube. |
| `crawled_at_utc` | Timestamp | No | Thời điểm crawl video. |

---

### 4.5 Bảng `youtube_comments` (Bình luận video)

* **Nguồn:** `s3://lakehouse/bronze/youtube/comments/`
* **Silver:** `silver_youtube_comments` (Làm sạch emoji/ký tự đặc biệt, lọc bình luận spam/quảng cáo).

| Tên cột | Kiểu dữ liệu | Nullable | Mô tả nghiệp vụ & Quy tắc Silver |
|---|---|---|---|
| `comment_id` | String | No | Khóa duy nhất (hoặc tạo hash từ `video_id + author + crawled_at`). |
| `video_id` | String | No | Khóa ngoại tham chiếu `silver_youtube_videos`. |
| `place_id` | String | No | Khóa ngoại tham chiếu `silver_places`. |
| `author_name` | String | Yes | Tên người dùng bình luận. |
| `comment_text` | String | No | Nội dung bình luận đã lọc rác. |
| `likes_count` | Integer | No | Số lượt thích bình luận (>= 0). |
| `crawled_at_utc` | Timestamp | No | Thời điểm thu thập. |

---

## 5. Chi tiết tầng GOLD (Data Warehouse / Star Schema & Marts)

Tầng Gold tổ chức theo mô hình chiều (Dimensional Modeling) phục vụ trực tiếp cho báo cáo BI, Dashboard và Huấn luyện mô hình (ML/NLP).

### 5.1 Các bảng Dimension (Chiều phân tích)

#### `dim_places`
* **Khóa chính:** `place_key` (Surrogate Key, sinh bằng hash MD5 của `place_id`).
* **Các trường:** `place_key`, `place_id`, `place_name`, `category`, `province_id`, `latitude`, `longitude`, `is_crawl_eligible`.

#### `dim_provinces`
* **Khóa chính:** `province_key`.
* **Các trường:** `province_key`, `province_id`, `province_name`, `region` (`Bắc`, `Trung`, `Nam`), `tourism_tier` (`Tier 1`, `Tier 2`, `Tier 3`).

#### `dim_date` (Chiều thời gian)
* **Khóa chính:** `date_key` (dạng số nguyên: `YYYYMMDD`, vd: `20261030`).
* **Các trường:** `date_key`, `full_date`, `day_of_week`, `day_name`, `month`, `month_name`, `quarter`, `year`, `is_weekend`, `is_vietnam_holiday` (cờ đánh dấu ngày Tết, 30/4-1/5, Quốc khánh...).

---

### 5.2 Các bảng Fact (Bảng sự kiện / Số đo)

#### `fact_place_reviews`
* **Grain:** Mỗi dòng đại diện cho 1 đánh giá của du khách trên Google Maps.
* **Khóa ngoại:** `date_key`, `place_key`, `province_key`.
* **Metrics:**
  - `rating`: Số sao (1 đến 5).
  - `likes_count`: Số lượt thích của review.
  - `review_length`: Độ dài văn bản đánh giá (số ký tự/từ).
  - `sentiment_score`: Điểm cảm xúc (nếu áp dụng model NLP: -1 tiêu cực, +1 tích cực).

#### `fact_youtube_engagement`
* **Grain:** Mỗi dòng đại diện cho 1 video du lịch được đăng tải và mức độ lan tỏa.
* **Khóa ngoại:** `published_date_key`, `crawl_date_key`, `place_key`, `province_key`.
* **Metrics:**
  - `views_count`: Lượt xem.
  - `duration_seconds`: Thời lượng video.
  - `comment_count`: Số bình luận thu thập được.

---

### 5.3 Các bảng Data Marts (Aggregations phục vụ Dashboard / Báo cáo)

#### `dm_place_monthly_reputation`
* **Mục đích:** Đánh giá danh tiếng và độ hài lòng của từng địa điểm du lịch qua từng tháng.
* **Trường thông tin:**
  - `year_month` (vd: `2026-08`)
  - `place_id`, `place_name`, `province_name`, `category`
  - `avg_rating`: Điểm đánh giá trung bình trong tháng.
  - `total_reviews_added`: Số đánh giá mới phát sinh trong tháng.
  - `negative_review_count`: Số review có điểm <= 2 sao.
  - `positive_review_count`: Số review có điểm >= 4 sao.

#### `dm_province_tourism_buzz`
* **Mục đích:** Đo lường mức độ quan tâm của cộng đồng mạng xã hội đối với các tỉnh/thành phố du lịch.
* **Trường thông tin:**
  - `province_name`, `region`
  - `total_places`: Tổng số địa điểm du lịch được số hóa.
  - `total_youtube_videos`: Số lượng video du lịch nhắc đến tỉnh.
  - `total_youtube_views`: Tổng lượt xem video về tỉnh.
  - `avg_province_rating`: Điểm đánh giá Google trung bình của các điểm trong tỉnh.
