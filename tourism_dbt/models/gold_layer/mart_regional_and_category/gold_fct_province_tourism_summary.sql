{{ config(materialized='table') }}

/*
    GOLD MART 3 - BẢNG FACT TỔNG HỢP HIỆU SUẤT DU LỊCH THEO TỈNH/THÀNH PHỐ (gold_fct_province_tourism_summary)
    Grain : 1 dòng / province_id (34 tỉnh/thành phố chuẩn từ silver_provinces).
    Mục đích:
      - Phục vụ trực tiếp cho biểu đồ bản đồ địa lý (Geo/Choropleth Map) và bảng xếp hạng năng lực
        cạnh tranh du lịch giữa 34 tỉnh/thành phố Việt Nam.
*/

WITH provinces AS (

    SELECT *
    FROM {{ ref('silver_provinces') }}

),

places_360 AS (

    SELECT *
    FROM {{ ref('gold_obt_place_360_profile') }}

),

province_agg AS (

    SELECT
        province_id,
        COUNT(*)                                                    AS total_places_count,
        COUNT(*) FILTER (
            WHERE crawled_review_count > 0
               OR youtube_video_count > 0
               OR COALESCE(latest_google_review_count, 0) > 0
        )                                                           AS active_places_count,
        COUNT(*) FILTER (WHERE is_forecast_eligible)                AS forecast_ready_places_count,
        COUNT(*) FILTER (
            WHERE place_development_stage = 'Leading Hotspot'
        )                                                           AS leading_hotspot_count,
        COUNT(*) FILTER (
            WHERE place_development_stage = 'Rising Star'
        )                                                           AS rising_star_count,

        CASE
            WHEN SUM(
                CASE
                    WHEN COALESCE(latest_google_rating, crawled_avg_rating) IS NOT NULL
                        THEN GREATEST(COALESCE(latest_google_review_count, crawled_review_count, 1), 1)
                    ELSE 0
                END
            ) > 0
                THEN ROUND(
                    SUM(
                        COALESCE(latest_google_rating, crawled_avg_rating)
                        * GREATEST(COALESCE(latest_google_review_count, crawled_review_count, 1), 1)
                    ) * 1.0
                    / SUM(
                        CASE
                            WHEN COALESCE(latest_google_rating, crawled_avg_rating) IS NOT NULL
                                THEN GREATEST(COALESCE(latest_google_review_count, crawled_review_count, 1), 1)
                            ELSE 0
                        END
                    ),
                    2
                )
        END                                                         AS province_weighted_avg_rating,
        ROUND(AVG(COALESCE(latest_google_rating, crawled_avg_rating)), 2)
                                                                    AS province_simple_avg_rating,
        COALESCE(SUM(latest_google_review_count), 0)                AS total_google_review_count,
        COALESCE(SUM(crawled_review_count), 0)                      AS total_crawled_review_count,
        ROUND(AVG(net_sentiment_score), 2)                          AS province_net_sentiment_score,

        COALESCE(SUM(youtube_video_count), 0)                       AS total_youtube_videos_count,
        COALESCE(SUM(total_youtube_views), 0)                       AS total_youtube_views,
        ROUND(AVG(total_youtube_views), 2)                          AS avg_views_per_place,
        SUM(total_youtube_views_delta)                              AS total_youtube_views_delta,
        ROUND(AVG(avg_daily_youtube_view_growth), 2)                AS province_avg_daily_view_growth

    FROM places_360
    GROUP BY province_id

),

top_place_views AS (

    SELECT
        province_id,
        place_id        AS top_place_id_by_views,
        place_name      AS top_place_name_by_views
    FROM places_360
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY province_id
        ORDER BY total_youtube_views DESC, crawled_review_count DESC, place_id ASC
    ) = 1

),

top_place_reviews AS (

    SELECT
        province_id,
        place_id        AS top_place_id_by_reviews,
        place_name      AS top_place_name_by_reviews
    FROM places_360
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY province_id
        ORDER BY COALESCE(latest_google_review_count, crawled_review_count, 0) DESC,
                 total_youtube_views DESC,
                 place_id ASC
    ) = 1

),

joined AS (

    SELECT
        pr.province_id,
        pr.province_name,
        pr.admin_scope,
        pr.center_lat,
        pr.center_lon,
        pr.min_lat,
        pr.max_lat,
        pr.min_lon,
        pr.max_lon,
        pr.geojson_url,

        COALESCE(pa.total_places_count, 0)                          AS total_places_count,
        COALESCE(pa.active_places_count, 0)                         AS active_places_count,
        COALESCE(pa.forecast_ready_places_count, 0)                 AS forecast_ready_places_count,
        COALESCE(pa.leading_hotspot_count, 0)                       AS leading_hotspot_count,
        COALESCE(pa.rising_star_count, 0)                           AS rising_star_count,

        pa.province_weighted_avg_rating,
        pa.province_simple_avg_rating,
        COALESCE(pa.total_google_review_count, 0)                   AS total_google_review_count,
        COALESCE(pa.total_crawled_review_count, 0)                  AS total_crawled_review_count,
        pa.province_net_sentiment_score,

        COALESCE(pa.total_youtube_videos_count, 0)                  AS total_youtube_videos_count,
        COALESCE(pa.total_youtube_views, 0)                         AS total_youtube_views,
        COALESCE(pa.avg_views_per_place, 0)                         AS avg_views_per_place,
        pa.total_youtube_views_delta,
        pa.province_avg_daily_view_growth,

        tv.top_place_id_by_views,
        tv.top_place_name_by_views,
        tr.top_place_id_by_reviews,
        tr.top_place_name_by_reviews,

        ROW_NUMBER() OVER (
            ORDER BY
                COALESCE(pa.total_google_review_count, 0)
                    + COALESCE(pa.total_crawled_review_count, 0) DESC,
                COALESCE(pa.total_youtube_views, 0) DESC,
                pr.province_id ASC
        )                                                           AS national_tourism_rank

    FROM provinces AS pr
    LEFT JOIN province_agg      AS pa ON pr.province_id = pa.province_id
    LEFT JOIN top_place_views   AS tv ON pr.province_id = tv.province_id
    LEFT JOIN top_place_reviews AS tr ON pr.province_id = tr.province_id

)

SELECT *
FROM joined
