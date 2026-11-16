{{ config(materialized='table') }}

/*
    GOLD MART 1 - BẢNG FACT QUỸ ĐẠO SNAPSHOT ĐỊA ĐIỂM (gold_fct_place_snapshot_trajectory)
    Grain : 1 dòng / (place_id, snapshot_date) trên trục lịch sử silver_google_maps_rating_snapshots (8.490 dòng).
    Mục đích:
      - Lấy chuỗi snapshot đánh giá Google Maps làm trục chuẩn (tránh hiện tượng 45%-55% NULL chéo do UNION
        hai lịch crawl bất đồng bộ giữa Google Maps và YouTube).
      - Kết hợp (As-Of / Nearest Snapshot Join) với trạng thái lượt xem YouTube của cùng địa điểm để phân tích
        đồng thời biến động Rating/Review và quy mô Lượt xem YouTube tại từng mốc snapshot.
*/

WITH primary_category AS (

    SELECT
        place_id,
        category_id         AS primary_category_id,
        category_group      AS primary_category_group,
        category_name       AS primary_category_name
    FROM {{ ref('silver_place_categories') }}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY place_id
        ORDER BY is_primary DESC NULLS LAST, category_id ASC
    ) = 1

),

rating_snapshots AS (

    SELECT
        place_id,
        snapshot_date,
        place_name,
        province_id,
        province_name,
        snapshot_seq_num,
        prev_snapshot_date,
        days_since_prev_snapshot,
        google_rating,
        prev_google_rating,
        rating_delta,
        google_review_count,
        prev_google_review_count,
        review_count_delta,
        CASE
            WHEN review_count_delta IS NOT NULL
             AND days_since_prev_snapshot IS NOT NULL
             AND days_since_prev_snapshot > 0
                THEN ROUND(review_count_delta * 1.0 / days_since_prev_snapshot, 2)
        END                                                         AS review_daily_velocity,
        rating_5_count,
        rating_4_count,
        rating_3_count,
        rating_2_count,
        rating_1_count,
        rating_distribution_total
    FROM {{ ref('silver_google_maps_rating_snapshots') }}

),

youtube_place_raw AS (

    SELECT
        place_id,
        snapshot_date,
        COUNT(DISTINCT video_id)                                    AS tracked_videos_count,
        SUM(views)                                                  AS total_youtube_views
    FROM {{ ref('silver_youtube_video_snapshots') }}
    GROUP BY place_id, snapshot_date

),

youtube_place_with_lag AS (

    SELECT
        *,
        LAG(snapshot_date) OVER (
            PARTITION BY place_id
            ORDER BY snapshot_date ASC
        )                                                           AS yt_prev_snapshot_date,
        LAG(total_youtube_views) OVER (
            PARTITION BY place_id
            ORDER BY snapshot_date ASC
        )                                                           AS prev_total_youtube_views
    FROM youtube_place_raw

),

youtube_place_snapshots AS (

    SELECT
        place_id,
        snapshot_date                                               AS youtube_snapshot_date,
        tracked_videos_count,
        total_youtube_views,
        prev_total_youtube_views,
        CASE
            WHEN total_youtube_views IS NOT NULL AND prev_total_youtube_views IS NOT NULL
                THEN total_youtube_views - prev_total_youtube_views
        END                                                         AS youtube_views_delta,
        CASE
            WHEN total_youtube_views IS NOT NULL
             AND prev_total_youtube_views IS NOT NULL
             AND yt_prev_snapshot_date IS NOT NULL
             AND DATE_DIFF('day', yt_prev_snapshot_date, snapshot_date) > 0
                THEN ROUND(
                    (total_youtube_views - prev_total_youtube_views) * 1.0
                    / DATE_DIFF('day', yt_prev_snapshot_date, snapshot_date),
                    2
                )
        END                                                         AS youtube_views_daily_growth
    FROM youtube_place_with_lag

),

matched_youtube_snapshot AS (

    -- Khớp mỗi đợt snapshot của địa điểm với kỳ snapshot YouTube gần nhất của chính địa điểm đó
    SELECT
        r.place_id,
        r.snapshot_date,
        y.youtube_snapshot_date,
        y.tracked_videos_count,
        y.total_youtube_views,
        y.prev_total_youtube_views,
        y.youtube_views_delta,
        y.youtube_views_daily_growth
    FROM rating_snapshots AS r
    INNER JOIN youtube_place_snapshots AS y
        ON r.place_id = y.place_id
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY r.place_id, r.snapshot_date
        ORDER BY
            CASE WHEN y.youtube_snapshot_date <= r.snapshot_date THEN 0 ELSE 1 END ASC,
            ABS(DATE_DIFF('day', y.youtube_snapshot_date, r.snapshot_date)) ASC
    ) = 1

),

joined AS (

    SELECT
        r.place_id || '|' || CAST(r.snapshot_date AS VARCHAR)       AS place_snapshot_id,
        r.place_id,
        COALESCE(p.place_name, r.place_name)                        AS place_name,
        COALESCE(p.province_id, r.province_id)                      AS province_id,
        COALESCE(p.province_name, r.province_name)                  AS province_name,
        (p.place_id IS NOT NULL)                                    AS is_place_in_dim,
        pc.primary_category_id,
        pc.primary_category_group,
        pc.primary_category_name,

        r.snapshot_date,
        r.snapshot_seq_num,
        r.prev_snapshot_date,
        r.days_since_prev_snapshot,

        -- Google Maps Rating Snapshot Metrics
        TRUE                                                        AS has_google_maps_snapshot,
        r.google_rating,
        r.prev_google_rating,
        r.rating_delta,
        r.google_review_count,
        r.prev_google_review_count,
        r.review_count_delta,
        r.review_daily_velocity,
        r.rating_5_count,
        r.rating_4_count,
        r.rating_3_count,
        r.rating_2_count,
        r.rating_1_count,
        r.rating_distribution_total,

        -- YouTube Video Snapshot Aggregated Metrics (Nearest/As-Of Matched)
        (y.place_id IS NOT NULL)                                    AS has_youtube_snapshot,
        COALESCE(y.tracked_videos_count, 0)                         AS tracked_videos_count,
        y.total_youtube_views,
        y.prev_total_youtube_views,
        y.youtube_views_delta,
        y.youtube_views_daily_growth

    FROM rating_snapshots AS r
    LEFT JOIN matched_youtube_snapshot AS y
        ON r.place_id = y.place_id AND r.snapshot_date = y.snapshot_date
    LEFT JOIN {{ ref('silver_places') }} AS p
        ON r.place_id = p.place_id
    LEFT JOIN primary_category AS pc
        ON r.place_id = pc.place_id

)

SELECT *
FROM joined
