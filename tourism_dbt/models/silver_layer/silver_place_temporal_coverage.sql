{{ config(materialized='table') }}

{%- set as_of_date_var = var('coverage_as_of_date', none) -%}
{%- set recent_days = var('coverage_recent_window_days', 90) -%}
{%- set min_history_months = var('coverage_min_history_months', 12) -%}
{%- set min_active_months = var('coverage_min_active_months', 6) -%}
{%- set sparse_max_active_months = var('coverage_sparse_max_active_months', 2) -%}
{%- set min_rating_snapshots = var('coverage_min_rating_snapshots', 2) %}

WITH places AS (

    SELECT
        place_id,
        place_name,
        province_id,
        province_name,
        crawl_eligible,
        tourism_status
    FROM {{ ref('silver_places') }}

),

-- BƯỚC 1
as_of AS (

    {% if as_of_date_var -%}
    SELECT CAST('{{ as_of_date_var }}' AS DATE) AS as_of_date
    {%- else -%}
    SELECT MAX(crawl_date) AS as_of_date
    FROM (
        SELECT MAX(CAST(crawled_at_utc AS DATE)) AS crawl_date FROM {{ ref('silver_travel_reviews') }}
        UNION ALL
        SELECT MAX(CAST(crawled_at_utc AS DATE)) FROM {{ ref('silver_youtube_videos') }}
        UNION ALL
        SELECT MAX(CAST(crawled_at_utc AS DATE)) FROM {{ ref('silver_youtube_comments') }}
        UNION ALL
        SELECT MAX(snapshot_date) FROM {{ ref('silver_google_maps_rating_snapshots') }}
    ) AS crawl_dates
    {%- endif %}

),

-- BƯỚC 2 
review_stats AS (

    SELECT
        place_id,
        COUNT(*)                                            AS review_count,
        COUNT(review_date)                                  AS review_dated_count,
        MIN(review_date)                                    AS review_min_date,
        MAX(review_date)                                    AS review_max_date,
        COUNT(DISTINCT review_month) FILTER (
            WHERE review_date_precision IN ('day', 'week', 'month')
        )                                                   AS review_active_month_count
    FROM {{ ref('silver_travel_reviews') }}
    GROUP BY place_id

),

video_stats AS (

    SELECT
        place_id,
        COUNT(DISTINCT video_id)                            AS video_count,
        MIN(published_date)                                 AS video_min_published_date,
        MAX(published_date)                                 AS video_max_published_date,
        COUNT(DISTINCT published_month)                     AS video_active_month_count
    FROM {{ ref('silver_youtube_videos') }}
    GROUP BY place_id

),

video_snapshot_stats AS (

    SELECT
        place_id,
        COUNT(*)                                            AS video_snapshot_count,
        COUNT(DISTINCT snapshot_date)                       AS video_snapshot_date_count,
        MIN(snapshot_date)                                  AS video_min_snapshot_date,
        MAX(snapshot_date)                                  AS video_max_snapshot_date
    FROM {{ ref('silver_youtube_video_snapshots') }}
    GROUP BY place_id

),

comment_stats AS (

    SELECT
        place_id,
        COUNT(*)                                            AS comment_count,
        COUNT(comment_created_date)                         AS comment_dated_count,
        MIN(comment_created_date)                           AS comment_min_date,
        MAX(comment_created_date)                           AS comment_max_date,
        COUNT(DISTINCT DATE_TRUNC('month', comment_created_date)) FILTER (
            WHERE comment_created_at_precision IN ('exact', 'day', 'week', 'month')
        )                                                   AS comment_active_month_count
    FROM {{ ref('silver_youtube_comments') }}
    GROUP BY place_id

),

rating_stats AS (

    SELECT
        place_id,
        COUNT(*)                                            AS rating_snapshot_count,
        MIN(snapshot_date)                                  AS rating_min_snapshot_date,
        MAX(snapshot_date)                                  AS rating_max_snapshot_date
    FROM {{ ref('silver_google_maps_rating_snapshots') }}
    GROUP BY place_id

),

-- BƯỚC 3
monthly_activity AS (

    SELECT place_id, review_month AS activity_month
    FROM {{ ref('silver_travel_reviews') }}
    WHERE review_month IS NOT NULL
      AND review_date_precision IN ('day', 'week', 'month')

    UNION

    SELECT place_id, published_month
    FROM {{ ref('silver_youtube_videos') }}
    WHERE published_month IS NOT NULL

    UNION

    SELECT place_id, CAST(DATE_TRUNC('month', comment_created_date) AS DATE)
    FROM {{ ref('silver_youtube_comments') }}
    WHERE comment_created_date IS NOT NULL
      AND comment_created_at_precision IN ('exact', 'day', 'week', 'month')

),

activity_stats AS (

    SELECT
        place_id,
        COUNT(DISTINCT activity_month) AS total_active_month_count
    FROM monthly_activity
    GROUP BY place_id

),

-- BƯỚC 4
joined AS (

    SELECT
        p.place_id,
        p.place_name,
        p.province_id,
        p.province_name,
        p.crawl_eligible,
        p.tourism_status,

        COALESCE(r.review_count, 0)                 AS review_count,
        COALESCE(r.review_dated_count, 0)           AS review_dated_count,
        r.review_min_date,
        r.review_max_date,
        COALESCE(r.review_active_month_count, 0)    AS review_active_month_count,

        COALESCE(v.video_count, 0)                  AS video_count,
        v.video_min_published_date,
        v.video_max_published_date,
        COALESCE(v.video_active_month_count, 0)     AS video_active_month_count,
        COALESCE(vs.video_snapshot_count, 0)        AS video_snapshot_count,
        COALESCE(vs.video_snapshot_date_count, 0)   AS video_snapshot_date_count,
        vs.video_min_snapshot_date,
        vs.video_max_snapshot_date,

        COALESCE(c.comment_count, 0)                AS comment_count,
        COALESCE(c.comment_dated_count, 0)          AS comment_dated_count,
        c.comment_min_date,
        c.comment_max_date,
        COALESCE(c.comment_active_month_count, 0)   AS comment_active_month_count,

        COALESCE(rt.rating_snapshot_count, 0)       AS rating_snapshot_count,
        rt.rating_min_snapshot_date,
        rt.rating_max_snapshot_date,

        COALESCE(a.total_active_month_count, 0)     AS total_active_month_count,
        ao.as_of_date

    FROM places AS p
    LEFT JOIN review_stats         AS r  ON p.place_id = r.place_id
    LEFT JOIN video_stats          AS v  ON p.place_id = v.place_id
    LEFT JOIN video_snapshot_stats AS vs ON p.place_id = vs.place_id
    LEFT JOIN comment_stats        AS c  ON p.place_id = c.place_id
    LEFT JOIN rating_stats         AS rt ON p.place_id = rt.place_id
    LEFT JOIN activity_stats       AS a  ON p.place_id = a.place_id
    CROSS JOIN as_of AS ao

),

-- BƯỚC 5
metrics AS (

    SELECT
        *,
        review_count + video_count + comment_count                            AS total_record_count,
        LEAST(review_min_date, video_min_published_date, comment_min_date)    AS first_activity_date,
        GREATEST(review_max_date, video_max_published_date, comment_max_date) AS last_activity_date
    FROM joined

),

flags AS (

    SELECT
        *,
        CASE
            WHEN first_activity_date IS NULL THEN 0
            ELSE DATE_DIFF('month', first_activity_date, last_activity_date) + 1
        END                                                                 AS history_span_months,
        CASE
            WHEN last_activity_date IS NULL OR as_of_date IS NULL THEN NULL
            ELSE DATE_DIFF('day', last_activity_date, as_of_date)
        END                                                                 AS days_since_last_activity
    FROM metrics

),

classified AS (

    SELECT
        *,
        (history_span_months >= {{ min_history_months }}
            AND total_active_month_count >= {{ min_active_months }})        AS has_temporal_history,
        COALESCE(days_since_last_activity <= {{ recent_days }}, FALSE)      AS has_recent_data,
        (total_record_count > 0
            AND total_active_month_count <= {{ sparse_max_active_months }}) AS is_sparse,
        (rating_snapshot_count >= {{ min_rating_snapshots }})               AS has_rating_history,
        (video_snapshot_date_count >= {{ min_rating_snapshots }})           AS has_video_view_history
    FROM flags

)

SELECT
    place_id,
    place_name,
    province_id,
    province_name,
    crawl_eligible,
    tourism_status,

    -- Google Maps reviews
    review_count,
    review_dated_count,
    review_min_date,
    review_max_date,
    review_active_month_count,

    -- YouTube videos
    video_count,
    video_min_published_date,
    video_max_published_date,
    video_active_month_count,
    video_snapshot_count,
    video_snapshot_date_count,
    video_min_snapshot_date,
    video_max_snapshot_date,

    -- YouTube comments
    comment_count,
    comment_dated_count,
    comment_min_date,
    comment_max_date,
    comment_active_month_count,

    -- Google Maps rating snapshots
    rating_snapshot_count,
    rating_min_snapshot_date,
    rating_max_snapshot_date,

    -- Tổng hợp
    total_record_count,
    total_active_month_count,
    first_activity_date,
    last_activity_date,
    history_span_months,
    days_since_last_activity,
    as_of_date,

    -- Phân loại
    has_temporal_history,
    has_recent_data,
    is_sparse,
    has_rating_history,
    has_video_view_history,
    CASE
        WHEN total_record_count = 0                         THEN 'no_data'
        WHEN has_temporal_history AND has_recent_data       THEN 'forecast_ready'
        WHEN is_sparse                                      THEN 'sparse'
        WHEN has_recent_data                                THEN 'recent_only'
        WHEN has_temporal_history                           THEN 'stale_history'
        ELSE 'partial'
    END                                                     AS coverage_status,
    (has_temporal_history AND has_recent_data)              AS is_forecast_eligible

FROM classified

