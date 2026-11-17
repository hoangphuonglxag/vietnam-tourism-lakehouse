{{ config(materialized='table') }}

/*
    GOLD MART 2 - BẢNG FACT HIỆU SUẤT & TĂNG TRƯỞNG VIDEO YOUTUBE (gold_fct_youtube_video_performance)
    Grain : 1 dòng / (place_id, video_id) — khớp 1-1 với silver_youtube_videos (35.215 bản ghi).
    Mục đích:
      - Đánh giá hiệu suất truyền thông và tốc độ tăng trưởng lượt xem của từng video quảng bá địa điểm
        qua các kỳ snapshot.
      - Xếp hạng các video có sức lan tỏa cao nhất cho từng địa điểm (place_video_view_rank).
*/

WITH videos AS (

    SELECT *
    FROM {{ ref('silver_youtube_videos') }}

),

snapshot_first AS (

    SELECT
        place_id,
        video_id,
        snapshot_date   AS first_snapshot_date,
        views           AS first_views
    FROM {{ ref('silver_youtube_video_snapshots') }}
    WHERE snapshot_seq_num = 1

),

snapshot_agg AS (

    SELECT
        place_id,
        video_id,
        COUNT(*)                                                    AS snapshot_count,
        MAX(snapshot_date)                                          AS latest_snapshot_date,
        SUM(views_delta) FILTER (WHERE snapshot_seq_num >= 2)       AS total_views_delta,
        ROUND(
            AVG(views_daily_growth) FILTER (WHERE snapshot_seq_num >= 2),
            2
        )                                                           AS snapshot_daily_view_growth
    FROM {{ ref('silver_youtube_video_snapshots') }}
    GROUP BY place_id, video_id

),

comment_agg AS (

    SELECT
        place_id,
        video_id,
        COUNT(*)                                                    AS crawled_comment_count
    FROM {{ ref('silver_youtube_comments') }}
    GROUP BY place_id, video_id

),

joined AS (

    SELECT
        v.place_id || '|' || v.video_id                             AS place_video_id,
        v.place_id,
        v.place_name,
        v.province_id,
        v.province_name,
        v.is_place_in_dim,

        v.video_id,
        v.video_title,
        v.channel_id,
        v.channel_name,
        v.category,
        v.video_url,

        v.published_date,
        v.published_month,
        v.duration_seconds,
        CASE
            WHEN v.published_date IS NOT NULL
             AND sa.latest_snapshot_date IS NOT NULL
             AND sa.latest_snapshot_date >= v.published_date
                THEN DATE_DIFF('day', v.published_date, sa.latest_snapshot_date)
        END                                                         AS video_age_days,

        sf.first_snapshot_date,
        sa.latest_snapshot_date,
        COALESCE(sa.snapshot_count, 1)                              AS snapshot_count,
        sf.first_views,
        v.views                                                     AS latest_views,
        sa.total_views_delta,
        CASE
            WHEN v.views IS NOT NULL
             AND v.published_date IS NOT NULL
             AND sa.latest_snapshot_date IS NOT NULL
             AND DATE_DIFF('day', v.published_date, sa.latest_snapshot_date) > 0
                THEN ROUND(
                    v.views * 1.0
                    / DATE_DIFF('day', v.published_date, sa.latest_snapshot_date),
                    2
                )
        END                                                         AS avg_daily_views_since_publish,
        sa.snapshot_daily_view_growth,
        COALESCE(ca.crawled_comment_count, 0)                       AS crawled_comment_count,

        ROW_NUMBER() OVER (
            PARTITION BY v.place_id
            ORDER BY v.views DESC NULLS LAST, v.published_date DESC NULLS LAST, v.video_id ASC
        )                                                           AS place_video_view_rank

    FROM videos AS v
    LEFT JOIN snapshot_first AS sf
        ON v.place_id = sf.place_id AND v.video_id = sf.video_id
    LEFT JOIN snapshot_agg AS sa
        ON v.place_id = sa.place_id AND v.video_id = sa.video_id
    LEFT JOIN comment_agg AS ca
        ON v.place_id = ca.place_id AND v.video_id = ca.video_id

)

SELECT *
FROM joined
