{{ config(materialized='table') }}

/*
    GOLD MART 3 - BẢNG FACT TỔNG HỢP HIỆU SUẤT THEO LOẠI HÌNH DU LỊCH (gold_fct_category_tourism_summary)
    Grain : 1 dòng / category_id (19 loại hình chuẩn từ silver_taxonomy).
    Mục đích:
      - Phân tích xu hướng thị hiếu du khách, mức độ hài lòng (rating & net sentiment) và sức hút truyền thông
        YouTube theo từng loại hình du lịch (Tâm linh, Sinh thái, Biển đảo, Văn hóa - Lịch sử, Giải trí...).
*/

WITH taxonomy AS (

    SELECT *
    FROM {{ ref('silver_taxonomy') }}

),

place_categories AS (

    SELECT *
    FROM {{ ref('silver_place_categories') }}

),

places_360 AS (

    SELECT *
    FROM {{ ref('gold_obt_place_360_profile') }}

),

category_agg AS (

    SELECT
        pc.category_id,
        COUNT(DISTINCT pc.place_id)                                 AS total_places_count,
        COUNT(DISTINCT pc.place_id) FILTER (WHERE pc.is_primary)    AS primary_places_count,
        COUNT(DISTINCT p.province_id)                               AS provinces_covered_count,

        CASE
            WHEN SUM(
                CASE
                    WHEN COALESCE(p.latest_google_rating, p.crawled_avg_rating) IS NOT NULL
                        THEN GREATEST(COALESCE(p.latest_google_review_count, p.crawled_review_count, 1), 1)
                    ELSE 0
                END
            ) > 0
                THEN ROUND(
                    SUM(
                        COALESCE(p.latest_google_rating, p.crawled_avg_rating)
                        * GREATEST(COALESCE(p.latest_google_review_count, p.crawled_review_count, 1), 1)
                    ) * 1.0
                    / SUM(
                        CASE
                            WHEN COALESCE(p.latest_google_rating, p.crawled_avg_rating) IS NOT NULL
                                THEN GREATEST(COALESCE(p.latest_google_review_count, p.crawled_review_count, 1), 1)
                            ELSE 0
                        END
                    ),
                    2
                )
        END                                                         AS category_weighted_avg_rating,
        ROUND(AVG(COALESCE(p.latest_google_rating, p.crawled_avg_rating)), 2)
                                                                    AS category_simple_avg_rating,
        COALESCE(SUM(p.latest_google_review_count), 0)              AS total_google_review_count,
        COALESCE(SUM(p.crawled_review_count), 0)                    AS total_crawled_review_count,
        ROUND(AVG(p.net_sentiment_score), 2)                        AS category_net_sentiment_score,

        COALESCE(SUM(p.youtube_video_count), 0)                     AS total_youtube_videos_count,
        COALESCE(SUM(p.total_youtube_views), 0)                     AS total_youtube_views,
        ROUND(AVG(p.total_youtube_views), 2)                        AS avg_views_per_place,
        SUM(p.total_youtube_views_delta)                            AS total_youtube_views_delta

    FROM place_categories AS pc
    LEFT JOIN places_360 AS p
        ON pc.place_id = p.place_id
    GROUP BY pc.category_id

),

top_place_per_cat AS (

    SELECT
        pc.category_id,
        p.place_id      AS top_place_id,
        p.place_name    AS top_place_name
    FROM place_categories AS pc
    INNER JOIN places_360 AS p
        ON pc.place_id = p.place_id
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY pc.category_id
        ORDER BY
            COALESCE(p.latest_google_review_count, p.crawled_review_count, 0) DESC,
            p.total_youtube_views DESC,
            p.place_id ASC
    ) = 1

),

joined AS (

    SELECT
        t.category_id,
        t.category_group,
        t.category_name,
        t.subcategory_name,
        t.name_vi,
        t.name_en,

        COALESCE(ca.total_places_count, 0)                          AS total_places_count,
        COALESCE(ca.primary_places_count, 0)                        AS primary_places_count,
        COALESCE(ca.provinces_covered_count, 0)                     AS provinces_covered_count,

        ca.category_weighted_avg_rating,
        ca.category_simple_avg_rating,
        COALESCE(ca.total_google_review_count, 0)                   AS total_google_review_count,
        COALESCE(ca.total_crawled_review_count, 0)                  AS total_crawled_review_count,
        ca.category_net_sentiment_score,

        COALESCE(ca.total_youtube_videos_count, 0)                  AS total_youtube_videos_count,
        COALESCE(ca.total_youtube_views, 0)                         AS total_youtube_views,
        COALESCE(ca.avg_views_per_place, 0)                         AS avg_views_per_place,
        ca.total_youtube_views_delta,

        tp.top_place_id,
        tp.top_place_name,

        ROW_NUMBER() OVER (
            ORDER BY
                COALESCE(ca.total_google_review_count, 0)
                    + COALESCE(ca.total_crawled_review_count, 0) DESC,
                COALESCE(ca.total_youtube_views, 0) DESC,
                t.category_id ASC
        )                                                           AS category_popularity_rank

    FROM taxonomy AS t
    LEFT JOIN category_agg      AS ca ON t.category_id = ca.category_id
    LEFT JOIN top_place_per_cat AS tp ON t.category_id = tp.category_id

)

SELECT *
FROM joined
