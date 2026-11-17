{% docs gold_fct_place_monthly_growth %}
### `gold_fct_place_monthly_growth` — Bảng Fact Tăng trưởng Địa điểm theo Tháng (Mart 1)

**Độ mịn (Grain):** `1 dòng / (place_id, activity_month)`.

**Mục đích:**
Theo dõi xu hướng phát triển dài hạn và tính mùa vụ (seasonality) của từng địa điểm qua từng tháng. Tổng hợp đồng thời động lượng đánh giá mới trên Google Maps, cảm xúc ròng của du khách (`monthly_net_sentiment_pct`), số lượng video YouTube mới xuất bản và các thước đo chuỗi thời gian (lũy kế, chênh lệch MoM, trung bình trượt 3 tháng).

**Các bước xử lý:**
1. Chọn danh mục chính (`primary_category`) cho từng `place_id` từ `silver_place_categories`.
2. Tổng hợp thống kê review theo `(place_id, review_month)` từ `silver_travel_reviews`.
3. Tổng hợp thống kê video xuất bản theo `(place_id, published_month)` từ `silver_youtube_videos` và bình luận từ `silver_youtube_comments`.
4. Hợp nhất trục thời gian tháng hoạt động (`place_months`), tính các hàm cửa sổ `SUM() OVER` (lũy kế), `LAG() OVER` (tăng trưởng MoM) và `AVG() OVER` (trung bình trượt 3 tháng).
{% enddocs %}


{% docs gold_fct_place_snapshot_trajectory %}
### `gold_fct_place_snapshot_trajectory` — Bảng Fact Quỹ đạo Snapshot Địa điểm (Mart 1)

**Độ mịn (Grain):** `1 dòng / (place_id, snapshot_date)`.

**Mục đích:**
Hợp nhất biến động Rating/Review trên Google Maps (`silver_google_maps_rating_snapshots`) và tăng trưởng tổng Lượt xem YouTube (`silver_youtube_video_snapshots`) của từng địa điểm tại mỗi mốc thu thập dữ liệu (`snapshot_date`). Phục vụ trực tiếp bài toán phân tích tốc độ tăng trưởng lượt xem (`youtube_views_daily_growth`) và tốc độ tăng đánh giá (`review_daily_velocity`, `rating_delta`) giữa các đợt crawl.
{% enddocs %}


{% docs gold_obt_place_360_profile %}
### `gold_obt_place_360_profile` — Bảng One Big Table Hồ sơ 360° Địa điểm Du lịch (Mart 2)

**Độ mịn (Grain):** `1 dòng / place_id` (đồng bộ 1-1 với `silver_places` và `silver_place_temporal_coverage` — 1.741 địa điểm chuẩn).

**Mục đích:**
Bảng trung tâm (Master Analytics OBT) cung cấp cái nhìn 360° về mỗi địa điểm du lịch:
- Thông tin địa lý & danh mục du lịch chính.
- Trạng thái Rating Google Maps mới nhất, biến động từ lần chụp đầu tiên (`total_rating_delta`, `rating_trend_direction`), phân bố tỷ lệ 1★–5★ và điểm Cảm xúc ròng (`net_sentiment_score`).
- Động lượng review văn bản 90 ngày gần nhất (`recent_review_momentum_pct`).
- Sức hút truyền thông YouTube (`total_youtube_views`, `total_youtube_views_delta`, `avg_daily_youtube_view_growth`, `views_growth_direction`).
- Xếp hạng trong tỉnh / toàn quốc và phân cụm giai đoạn phát triển chiến lược (`place_development_stage`: `Leading Hotspot`, `Established Destination`, `Rising Star`, `Steady Destination`, `Cooling / At Risk`, `Emerging / Low Data`).
{% enddocs %}


{% docs gold_fct_youtube_video_performance %}
### `gold_fct_youtube_video_performance` — Bảng Fact Hiệu suất & Tăng trưởng Video YouTube (Mart 2)

**Độ mịn (Grain):** `1 dòng / (place_id, video_id)` (đồng bộ 1-1 với `silver_youtube_videos` — 35.215 bản ghi).

**Mục đích:**
Đánh giá hiệu suất truyền thông, tuổi đời video, tổng mức tăng trưởng lượt xem qua các đợt snapshot (`total_views_delta`, `snapshot_daily_view_growth`), tốc độ thu hút lượt xem trung bình mỗi ngày kể từ khi đăng (`avg_daily_views_since_publish`) và thứ hạng sức hút của video trong từng địa điểm (`place_video_view_rank`).
{% enddocs %}


{% docs gold_fct_province_tourism_summary %}
### `gold_fct_province_tourism_summary` — Bảng Fact Tổng hợp Hiệu suất Du lịch theo Tỉnh/Thành phố (Mart 3)

**Độ mịn (Grain):** `1 dòng / province_id` (đồng bộ 1-1 với `silver_provinces` — 34 tỉnh/thành phố).

**Mục đích:**
Phục vụ biểu đồ bản đồ Việt Nam (Geo/Choropleth Map) và bảng xếp hạng năng lực cạnh tranh du lịch cấp tỉnh/thành phố (`national_tourism_rank`), bao gồm quy mô điểm đến, số lượng `Leading Hotspot` / `Rising Star`, điểm đánh giá trung bình gia quyền (`province_weighted_avg_rating`), điểm cảm xúc ròng, tổng lượt xem YouTube và địa điểm dẫn đầu của mỗi tỉnh.
{% enddocs %}


{% docs gold_fct_category_tourism_summary %}
### `gold_fct_category_tourism_summary` — Bảng Fact Tổng hợp Hiệu suất theo Loại hình Du lịch (Mart 3)

**Độ mịn (Grain):** `1 dòng / category_id` (đồng bộ 1-1 với `silver_taxonomy` — 19 loại hình du lịch).

**Mục đích:**
So sánh xu hướng thị hiếu du khách, mức độ hài lòng (`category_weighted_avg_rating`, `category_net_sentiment_score`) và sức hút truyền thông YouTube (`total_youtube_views`, `avg_views_per_place`) giữa 19 danh mục loại hình du lịch.
{% enddocs %}
