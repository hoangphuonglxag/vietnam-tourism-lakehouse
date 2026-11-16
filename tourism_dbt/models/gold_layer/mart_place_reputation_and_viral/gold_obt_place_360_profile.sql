{{ config(materialized='table') }}

/*
    GOLD MART 2 - BẢNG ONE BIG TABLE HỒ SƠ 360° ĐỊA ĐIỂM DU LỊCH (gold_obt_place_360_profile)
    Grain : 1 dòng / place_id (1.741 địa điểm chuẩn từ silver_places, đồng bộ 1-1 với silver_place_temporal_coverage).
    Mục đích:
      - Tích hợp toàn diện thông tin địa lý, danh mục du lịch, uy tín Google Maps (rating & phân bố sao),
        động lượng review văn bản, sức hút truyền thông YouTube, độ phủ thời gian và phân cụm xu hướng phát triển
        (place_development_stage).
*/

{%- set rating_trend_threshold = var('gold_rating_trend_threshold', 0.05) -%}
{%- set momentum_decline_pct = var('gold_review_momentum_decline_pct', -30) -%}
{%- set momentum_growth_pct = var('gold_review_momentum_growth_pct', 20) -%}
{%- set momentum_min_reviews = var('gold_review_momentum_min_reviews', 5) -%}

WITH places AS (

    SELECT *
    FROM {{ ref('silver_places') }}

),

coverage AS (

    SELECT *
    FROM {{ ref('silver_place_temporal_coverage') }}

),

primary_category AS (

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

category_counts AS (

    SELECT
        place_id,
        COUNT(DISTINCT category_id) AS category_count
    FROM {{ ref('silver_place_categories') }}
    GROUP BY place_id

),

rating_latest AS (

    SELECT
        place_id,
        snapshot_date               AS latest_rating_snapshot_date,
        google_rating               AS latest_google_rating,
        google_review_count         AS latest_google_review_count,
        rating_5_count,
        rating_4_count,
        rating_3_count,
        rating_2_count,
        rating_1_count,
        rating_distribution_total
    FROM {{ ref('silver_google_maps_rating_snapshots') }}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY place_id
        ORDER BY snapshot_date DESC, crawled_at_utc DESC
    ) = 1

),

rating_first AS (

    SELECT
        place_id,
        snapshot_date               AS first_rating_snapshot_date,
        google_rating               AS first_google_rating,
        google_review_count         AS first_google_review_count
    FROM {{ ref('silver_google_maps_rating_snapshots') }}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY place_id
        ORDER BY snapshot_date ASC, crawled_at_utc ASC
    ) = 1

),

review_summary AS (

    SELECT
        r.place_id,
        COUNT(*)                                                    AS crawled_review_count,
        ROUND(AVG(r.rating), 2)                                     AS crawled_avg_rating,
        COUNT(*) FILTER (WHERE r.has_review_text)                   AS text_review_count,
        COUNT(r.rating)                                             AS rated_review_count,
        COUNT(*) FILTER (WHERE r.rating >= 4)                       AS positive_review_count,
        COUNT(*) FILTER (WHERE r.rating <= 2)                       AS negative_review_count,
        COUNT(*) FILTER (
            WHERE r.review_date IS NOT NULL
              AND r.review_date > c.as_of_date - INTERVAL 90 DAY
        )                                                           AS reviews_last_90d_count,
        COUNT(*) FILTER (
            WHERE r.review_date IS NOT NULL
              AND r.review_date > c.as_of_date - INTERVAL 180 DAY
              AND r.review_date <= c.as_of_date - INTERVAL 90 DAY
        )                                                           AS reviews_prev_90d_count
    FROM {{ ref('silver_travel_reviews') }} AS r
    INNER JOIN coverage AS c
        ON r.place_id = c.place_id
    GROUP BY r.place_id

),

video_summary AS (

    SELECT
        place_id,
        COUNT(DISTINCT video_id)                                    AS youtube_video_count,
        COUNT(DISTINCT channel_id)                                  AS distinct_channel_count,
        COALESCE(SUM(views), 0)                                     AS total_youtube_views,
        ROUND(AVG(views), 2)                                        AS avg_views_per_video,
        MAX(views)                                                  AS max_video_views
    FROM {{ ref('silver_youtube_videos') }}
    GROUP BY place_id

),

top_video AS (

    SELECT
        place_id,
        video_id                                                    AS top_video_id,
        video_title                                                 AS top_video_title
    FROM {{ ref('silver_youtube_videos') }}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY place_id
        ORDER BY views DESC NULLS LAST, published_date DESC NULLS LAST, video_id ASC
    ) = 1

),

video_growth_summary AS (

    SELECT
        place_id,
        SUM(views_delta)                                            AS total_youtube_views_delta,
        ROUND(AVG(views_daily_growth), 2)                           AS avg_daily_youtube_view_growth
    FROM {{ ref('silver_youtube_video_snapshots') }}
    WHERE snapshot_seq_num >= 2
    GROUP BY place_id

),

assembled AS (

    SELECT
        p.place_id,
        p.place_name,
        p.name_vi,
        p.name_en,
        p.province_id,
        p.province_name,
        p.admin_scope,
        p.latitude,
        p.longitude,
        p.tourism_status,
        p.crawl_eligible,

        pc.primary_category_id,
        pc.primary_category_group,
        pc.primary_category_name,
        COALESCE(cc.category_count, 0)                              AS category_count,

        -- Google Maps Rating Snapshot Metrics
        rl.latest_google_rating,
        rl.latest_google_review_count,
        rl.latest_rating_snapshot_date,
        rf.first_google_rating,
        rf.first_google_review_count,
        rf.first_rating_snapshot_date,
        CASE
            WHEN cov.rating_snapshot_count >= 2
             AND rl.latest_google_rating IS NOT NULL
             AND rf.first_google_rating IS NOT NULL
                THEN ROUND(rl.latest_google_rating - rf.first_google_rating, 4)
        END                                                         AS total_rating_delta,
        CASE
            WHEN cov.rating_snapshot_count >= 2
             AND rl.latest_google_review_count IS NOT NULL
             AND rf.first_google_review_count IS NOT NULL
                THEN rl.latest_google_review_count - rf.first_google_review_count
        END                                                         AS total_review_count_delta,

        CASE
            WHEN COALESCE(rl.rating_distribution_total, 0) > 0
                THEN ROUND(COALESCE(rl.rating_5_count, 0) * 100.0 / rl.rating_distribution_total, 2)
        END                                                         AS rating_5_pct,
        CASE
            WHEN COALESCE(rl.rating_distribution_total, 0) > 0
                THEN ROUND(COALESCE(rl.rating_4_count, 0) * 100.0 / rl.rating_distribution_total, 2)
        END                                                         AS rating_4_pct,
        CASE
            WHEN COALESCE(rl.rating_distribution_total, 0) > 0
                THEN ROUND(COALESCE(rl.rating_3_count, 0) * 100.0 / rl.rating_distribution_total, 2)
        END                                                         AS rating_3_pct,
        CASE
            WHEN COALESCE(rl.rating_distribution_total, 0) > 0
                THEN ROUND(COALESCE(rl.rating_2_count, 0) * 100.0 / rl.rating_distribution_total, 2)
        END                                                         AS rating_2_pct,
        CASE
            WHEN COALESCE(rl.rating_distribution_total, 0) > 0
                THEN ROUND(COALESCE(rl.rating_1_count, 0) * 100.0 / rl.rating_distribution_total, 2)
        END                                                         AS rating_1_pct,

        CASE
            WHEN COALESCE(rl.rating_distribution_total, 0) > 0
                THEN ROUND(
                    (COALESCE(rl.rating_5_count, 0) + COALESCE(rl.rating_4_count, 0)
                     - COALESCE(rl.rating_1_count, 0) - COALESCE(rl.rating_2_count, 0))
                    * 100.0 / rl.rating_distribution_total,
                    2
                )
            WHEN COALESCE(rv.rated_review_count, 0) > 0
                THEN ROUND(
                    (COALESCE(rv.positive_review_count, 0) - COALESCE(rv.negative_review_count, 0))
                    * 100.0 / rv.rated_review_count,
                    2
                )
        END                                                         AS net_sentiment_score,

        -- Crawled Review Metrics
        COALESCE(rv.crawled_review_count, 0)                        AS crawled_review_count,
        rv.crawled_avg_rating,
        CASE
            WHEN COALESCE(rv.crawled_review_count, 0) > 0
                THEN ROUND(COALESCE(rv.text_review_count, 0) * 100.0 / rv.crawled_review_count, 2)
        END                                                         AS text_review_ratio,
        COALESCE(rv.reviews_last_90d_count, 0)                      AS reviews_last_90d_count,
        COALESCE(rv.reviews_prev_90d_count, 0)                      AS reviews_prev_90d_count,
        CASE
            WHEN COALESCE(rv.reviews_prev_90d_count, 0) > 0
                THEN ROUND(
                    (COALESCE(rv.reviews_last_90d_count, 0) - rv.reviews_prev_90d_count)
                    * 100.0 / rv.reviews_prev_90d_count,
                    2
                )
        END                                                         AS recent_review_momentum_pct,

        -- YouTube Video & Growth Metrics
        COALESCE(vs.youtube_video_count, 0)                         AS youtube_video_count,
        COALESCE(vs.distinct_channel_count, 0)                      AS distinct_channel_count,
        COALESCE(vs.total_youtube_views, 0)                         AS total_youtube_views,
        vs.avg_views_per_video,
        vs.max_video_views,
        tv.top_video_id,
        tv.top_video_title,
        vg.total_youtube_views_delta,
        vg.avg_daily_youtube_view_growth,

        -- Coverage & Temporal Metadata
        cov.rating_snapshot_count,
        cov.video_snapshot_date_count,
        cov.total_active_month_count,
        cov.history_span_months,
        cov.coverage_status,
        cov.is_forecast_eligible

    FROM places AS p
    INNER JOIN coverage             AS cov ON p.place_id = cov.place_id
    LEFT JOIN primary_category      AS pc  ON p.place_id = pc.place_id
    LEFT JOIN category_counts       AS cc  ON p.place_id = cc.place_id
    LEFT JOIN rating_latest         AS rl  ON p.place_id = rl.place_id
    LEFT JOIN rating_first          AS rf  ON p.place_id = rf.place_id
    LEFT JOIN review_summary        AS rv  ON p.place_id = rv.place_id
    LEFT JOIN video_summary         AS vs  ON p.place_id = vs.place_id
    LEFT JOIN top_video             AS tv  ON p.place_id = tv.place_id
    LEFT JOIN video_growth_summary  AS vg  ON p.place_id = vg.place_id

),

classified AS (

    SELECT
        *,
        CASE
            WHEN rating_snapshot_count = 0 OR latest_google_rating IS NULL  THEN 'no_data'
            WHEN rating_snapshot_count = 1 OR total_rating_delta IS NULL    THEN 'single_snapshot'
            WHEN total_rating_delta >= {{ rating_trend_threshold }}         THEN 'improving'
            WHEN total_rating_delta <= -{{ rating_trend_threshold }}        THEN 'declining'
            ELSE 'stable'
        END                                                                 AS rating_trend_direction,

        CASE
            WHEN youtube_video_count = 0                                    THEN 'no_video'
            WHEN video_snapshot_date_count < 2                              THEN 'single_snapshot'
            WHEN COALESCE(total_youtube_views_delta, 0) > 0
             AND COALESCE(avg_daily_youtube_view_growth, 0) >= 100          THEN 'surging'
            WHEN COALESCE(total_youtube_views_delta, 0) > 0                 THEN 'growing'
            WHEN COALESCE(total_youtube_views_delta, 0) = 0                 THEN 'steady'
            ELSE 'stagnant'
        END                                                                 AS views_growth_direction,

        ROW_NUMBER() OVER (
            PARTITION BY province_id
            ORDER BY
                COALESCE(latest_google_review_count, crawled_review_count, 0) DESC,
                total_youtube_views DESC,
                place_id ASC
        )                                                                   AS province_popularity_rank,

        ROW_NUMBER() OVER (
            ORDER BY
                COALESCE(latest_google_review_count, crawled_review_count, 0) DESC,
                total_youtube_views DESC,
                place_id ASC
        )                                                                   AS national_popularity_rank

    FROM assembled

)

SELECT
    place_id,
    place_name,
    name_vi,
    name_en,
    province_id,
    province_name,
    admin_scope,
    latitude,
    longitude,
    tourism_status,
    crawl_eligible,

    primary_category_id,
    primary_category_group,
    primary_category_name,
    category_count,

    latest_google_rating,
    latest_google_review_count,
    latest_rating_snapshot_date,
    first_google_rating,
    first_google_review_count,
    first_rating_snapshot_date,
    total_rating_delta,
    total_review_count_delta,
    rating_5_pct,
    rating_4_pct,
    rating_3_pct,
    rating_2_pct,
    rating_1_pct,
    net_sentiment_score,
    rating_trend_direction,

    crawled_review_count,
    crawled_avg_rating,
    text_review_ratio,
    reviews_last_90d_count,
    reviews_prev_90d_count,
    recent_review_momentum_pct,

    youtube_video_count,
    distinct_channel_count,
    total_youtube_views,
    avg_views_per_video,
    max_video_views,
    top_video_id,
    top_video_title,
    total_youtube_views_delta,
    avg_daily_youtube_view_growth,
    views_growth_direction,

    coverage_status,
    is_forecast_eligible,
    total_active_month_count,
    history_span_months,
    province_popularity_rank,
    national_popularity_rank,

    CASE
        WHEN coverage_status IN ('no_data', 'sparse')
          OR (COALESCE(latest_google_review_count, crawled_review_count, 0) < 10
              AND total_youtube_views < 1000)
            THEN 'Emerging / Low Data'
        WHEN rating_trend_direction = 'declining'
          OR COALESCE(latest_google_rating, crawled_avg_rating, 5.0) < 3.5
          OR (COALESCE(recent_review_momentum_pct, 0) <= {{ momentum_decline_pct }}
              AND reviews_prev_90d_count >= {{ momentum_min_reviews }})
            THEN 'Cooling / At Risk'
        WHEN (COALESCE(latest_google_review_count, crawled_review_count, 0) >= 500
              OR total_youtube_views >= 500000)
         AND (rating_trend_direction = 'improving'
              OR views_growth_direction IN ('surging', 'growing')
              OR COALESCE(recent_review_momentum_pct, 0) >= {{ momentum_growth_pct }}
              OR reviews_last_90d_count >= 10)
            THEN 'Leading Hotspot'
        WHEN (COALESCE(latest_google_review_count, crawled_review_count, 0) >= 500
              OR total_youtube_views >= 500000)
            THEN 'Established Destination'
        WHEN rating_trend_direction = 'improving'
          OR views_growth_direction IN ('surging', 'growing')
          OR COALESCE(recent_review_momentum_pct, 0) >= {{ momentum_growth_pct }}
          OR reviews_last_90d_count >= {{ momentum_min_reviews }}
            THEN 'Rising Star'
        ELSE 'Steady Destination'
    END                                                                     AS place_development_stage

FROM classified
