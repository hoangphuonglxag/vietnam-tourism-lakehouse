{{ config(materialized='table') }}

/*
    SILVER - YOUTUBE VIDEO SNAPSHOTS (chuỗi thời gian lượt xem video theo ngày crawl)
    Grain : 1 dòng / (place_id, video_id, snapshot_date).
    Mục đích: Theo dõi sự tăng trưởng lượt xem (views) của từng video và địa điểm qua các đợt crawl
              (khác với silver_youtube_videos chỉ giữ trạng thái mới nhất của mỗi video).
    Các bước (chi tiết xem doc block `silver_youtube_video_snapshots`):
      1. Lọc bản ghi hợp lệ + xác định snapshot_date = CAST(crawled_at_utc AS DATE).
      2. Khử trùng lặp theo (place_id, video_id, snapshot_date), giữ lần crawl mới nhất trong ngày.
      3. Kiểm tra miền giá trị (views >= 0, duration_seconds >= 0, published_at_utc không ở tương lai).
      4. Dùng hàm cửa sổ LAG() theo (place_id, video_id) để tính biến động lượt xem giữa các đợt crawl:
         prev_snapshot_date, prev_views, views_delta, views_daily_growth.
      5. LEFT JOIN silver_places để chuẩn hóa place/province.
*/

WITH valid_records AS (

    -- BƯỚC 1: lọc bản ghi hợp lệ + xác định ngày snapshot
    SELECT
        *,
        CAST(crawled_at_utc AS DATE) AS snapshot_date
    FROM {{ ref('stg_youtube_videos') }}
    WHERE place_id IS NOT NULL
      AND video_id IS NOT NULL
      AND crawled_at_utc IS NOT NULL
      AND COALESCE(bronze_record_status, 'success') = 'success'

),

deduplicated AS (

    -- BƯỚC 2: nếu 1 video của 1 place được crawl nhiều lần trong cùng 1 ngày, giữ lần mới nhất
    {{ deduplicate_by_key(
        'valid_records',
        ['place_id', 'video_id', 'snapshot_date'],
        'crawled_at_utc DESC, bronze_ingested_at_utc DESC NULLS LAST'
    ) }}

),

cleaned AS (

    -- BƯỚC 3: kiểm tra miền giá trị
    SELECT
        place_id,
        place_name,
        province_id,
        province_name,
        video_id,
        video_title,
        channel_id,
        channel_name,
        search_query,
        snapshot_date,
        crawled_at_utc,
        CASE WHEN views >= 0 THEN views END                         AS views,
        CASE WHEN duration_seconds >= 0 THEN duration_seconds END   AS duration_seconds,
        category,
        video_url,
        CASE
            WHEN published_at_utc > crawled_at_utc + INTERVAL 1 DAY THEN NULL
            ELSE published_at_utc
        END                                                         AS published_at_utc,
        bronze_run_id
    FROM deduplicated

),

with_growth AS (

    -- BƯỚC 4: tính tốc độ tăng trưởng lượt xem giữa các lần snapshot của cùng (place_id, video_id)
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY place_id, video_id
            ORDER BY snapshot_date ASC
        )                                                           AS snapshot_seq_num,
        LAG(snapshot_date) OVER (
            PARTITION BY place_id, video_id
            ORDER BY snapshot_date ASC
        )                                                           AS prev_snapshot_date,
        LAG(views) OVER (
            PARTITION BY place_id, video_id
            ORDER BY snapshot_date ASC
        )                                                           AS prev_views
    FROM cleaned

),

with_deltas AS (

    SELECT
        *,
        CASE
            WHEN prev_snapshot_date IS NOT NULL
                THEN DATE_DIFF('day', prev_snapshot_date, snapshot_date)
        END                                                         AS days_since_prev_snapshot,
        CASE
            WHEN views IS NOT NULL AND prev_views IS NOT NULL
                THEN views - prev_views
        END                                                         AS views_delta,
        CASE
            WHEN views IS NOT NULL
             AND prev_views IS NOT NULL
             AND prev_snapshot_date IS NOT NULL
             AND DATE_DIFF('day', prev_snapshot_date, snapshot_date) > 0
                THEN ROUND(
                    (views - prev_views) * 1.0
                    / DATE_DIFF('day', prev_snapshot_date, snapshot_date),
                    2
                )
        END                                                         AS views_daily_growth
    FROM with_growth

),

enriched AS (

    -- BƯỚC 5: chuẩn hóa place/province theo silver_places
    SELECT
        w.place_id || '|' || w.video_id || '|' || CAST(w.snapshot_date AS VARCHAR)
                                                                    AS video_snapshot_id,
        w.place_id,
        COALESCE(p.place_name, w.place_name)                        AS place_name,
        COALESCE(p.province_id, w.province_id)                      AS province_id,
        COALESCE(p.province_name, w.province_name)                  AS province_name,
        (p.place_id IS NOT NULL)                                    AS is_place_in_dim,

        w.video_id,
        w.video_title,
        w.channel_id,
        w.channel_name,
        w.search_query,
        w.category,
        w.video_url,

        w.published_at_utc,
        CAST(w.published_at_utc AS DATE)                            AS published_date,
        w.snapshot_date,
        w.crawled_at_utc,

        w.views,
        w.duration_seconds,
        w.snapshot_seq_num,
        w.prev_snapshot_date,
        w.days_since_prev_snapshot,
        w.prev_views,
        w.views_delta,
        w.views_daily_growth,

        'youtube'                                                   AS source,
        w.bronze_run_id

    FROM with_deltas AS w
    LEFT JOIN {{ ref('silver_places') }} AS p
        ON w.place_id = p.place_id

)

SELECT *
FROM enriched

