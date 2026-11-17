{{ config(materialized='table') }}

/*
    GOLD MART 1 - BẢNG FACT TĂNG TRƯỞNG ĐỊA ĐIỂM THEO THÁNG (gold_fct_place_monthly_growth)
    Grain : 1 dòng / (place_id, activity_month).
    Mục đích:
      - Theo dõi xu hướng phát triển dài hạn và tính mùa vụ (seasonality) của từng địa điểm qua từng tháng.
      - Tính toán động lượng review mới, tỷ lệ cảm xúc ròng (Net Sentiment %), lượng video YouTube xuất bản
        và tốc độ tăng trưởng luỹ kế / Month-over-Month (MoM).
      - Bảo toàn Expected NULL theo đúng nghiệp vụ: tháng không phát sinh review thì monthly_avg_review_rating
        và monthly_net_sentiment_pct giữ nguyên NULL; kỳ hoạt động đầu tiên giữ nguyên prev_month_reviews_count = NULL.
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

review_monthly AS (

    SELECT
        place_id,
        review_month                                                AS activity_month,
        MAX(place_name)                                             AS place_name,
        MAX(province_id)                                            AS province_id,
        MAX(province_name)                                          AS province_name,
        COUNT(*)                                                    AS new_reviews_count,
        COUNT(*) FILTER (WHERE has_review_text)                     AS new_reviews_with_text_count,
        COUNT(rating)                                               AS rated_reviews_count,
        ROUND(AVG(rating), 2)                                       AS monthly_avg_review_rating,
        COUNT(*) FILTER (WHERE rating >= 4)                         AS positive_reviews_count,
        COUNT(*) FILTER (WHERE rating = 3)                          AS neutral_reviews_count,
        COUNT(*) FILTER (WHERE rating <= 2)                         AS negative_reviews_count,
        COALESCE(SUM(likes_count), 0)                               AS review_likes_sum
    FROM {{ ref('silver_travel_reviews') }}
    WHERE review_month IS NOT NULL
    GROUP BY place_id, review_month

),

video_monthly AS (

    SELECT
        place_id,
        published_month                                             AS activity_month,
        MAX(place_name)                                             AS place_name,
        MAX(province_id)                                            AS province_id,
        MAX(province_name)                                          AS province_name,
        COUNT(DISTINCT video_id)                                    AS new_videos_published_count,
        COALESCE(SUM(views), 0)                                     AS new_videos_current_views_sum
    FROM {{ ref('silver_youtube_videos') }}
    WHERE published_month IS NOT NULL
    GROUP BY place_id, published_month

),

comment_monthly AS (

    SELECT
        place_id,
        CAST(DATE_TRUNC('month', comment_created_date) AS DATE)     AS activity_month,
        COUNT(*)                                                    AS new_comments_count
    FROM {{ ref('silver_youtube_comments') }}
    WHERE comment_created_date IS NOT NULL
    GROUP BY place_id, CAST(DATE_TRUNC('month', comment_created_date) AS DATE)

),

place_months AS (

    SELECT place_id, activity_month FROM review_monthly
    UNION
    SELECT place_id, activity_month FROM video_monthly
    UNION
    SELECT place_id, activity_month FROM comment_monthly

),

combined AS (

    SELECT
        pm.place_id,
        COALESCE(r.place_name, v.place_name)                        AS fallback_place_name,
        COALESCE(r.province_id, v.province_id)                      AS fallback_province_id,
        COALESCE(r.province_name, v.province_name)                  AS fallback_province_name,
        pm.activity_month,
        EXTRACT(YEAR FROM pm.activity_month)                        AS activity_year,
        EXTRACT(QUARTER FROM pm.activity_month)                     AS activity_quarter,

        COALESCE(r.new_reviews_count, 0)                            AS new_reviews_count,
        COALESCE(r.new_reviews_with_text_count, 0)                  AS new_reviews_with_text_count,
        COALESCE(r.rated_reviews_count, 0)                          AS rated_reviews_count,
        r.monthly_avg_review_rating,
        COALESCE(r.positive_reviews_count, 0)                       AS positive_reviews_count,
        COALESCE(r.neutral_reviews_count, 0)                        AS neutral_reviews_count,
        COALESCE(r.negative_reviews_count, 0)                       AS negative_reviews_count,
        CASE
            WHEN COALESCE(r.rated_reviews_count, 0) > 0
                THEN ROUND(
                    (COALESCE(r.positive_reviews_count, 0) - COALESCE(r.negative_reviews_count, 0))
                    * 100.0 / r.rated_reviews_count,
                    2
                )
        END                                                         AS monthly_net_sentiment_pct,
        COALESCE(r.review_likes_sum, 0)                             AS review_likes_sum,

        COALESCE(v.new_videos_published_count, 0)                   AS new_videos_published_count,
        COALESCE(v.new_videos_current_views_sum, 0)                 AS new_videos_current_views_sum,
        COALESCE(c.new_comments_count, 0)                           AS new_comments_count

    FROM place_months AS pm
    LEFT JOIN review_monthly  AS r ON pm.place_id = r.place_id AND pm.activity_month = r.activity_month
    LEFT JOIN video_monthly   AS v ON pm.place_id = v.place_id AND pm.activity_month = v.activity_month
    LEFT JOIN comment_monthly AS c ON pm.place_id = c.place_id AND pm.activity_month = c.activity_month

),

with_window_metrics AS (

    SELECT
        *,
        SUM(new_reviews_count) OVER (
            PARTITION BY place_id
            ORDER BY activity_month ASC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )                                                           AS cumulative_reviews_count,
        SUM(new_videos_published_count) OVER (
            PARTITION BY place_id
            ORDER BY activity_month ASC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )                                                           AS cumulative_videos_count,
        LAG(new_reviews_count) OVER (
            PARTITION BY place_id
            ORDER BY activity_month ASC
        )                                                           AS prev_month_reviews_count,
        ROUND(
            AVG(new_reviews_count) OVER (
                PARTITION BY place_id
                ORDER BY activity_month ASC
                ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
            ),
            2
        )                                                           AS rolling_3m_reviews_avg
    FROM combined

),

enriched AS (

    SELECT
        w.place_id || '|' || CAST(w.activity_month AS VARCHAR)      AS place_month_id,
        w.place_id,
        COALESCE(p.place_name, w.fallback_place_name)               AS place_name,
        COALESCE(p.province_id, w.fallback_province_id)             AS province_id,
        COALESCE(p.province_name, w.fallback_province_name)         AS province_name,
        (p.place_id IS NOT NULL)                                    AS is_place_in_dim,
        pc.primary_category_id,
        pc.primary_category_group,
        pc.primary_category_name,

        w.activity_month,
        w.activity_year,
        w.activity_quarter,

        w.new_reviews_count,
        w.new_reviews_with_text_count,
        w.monthly_avg_review_rating,
        w.positive_reviews_count,
        w.neutral_reviews_count,
        w.negative_reviews_count,
        w.monthly_net_sentiment_pct,
        w.review_likes_sum,

        w.new_videos_published_count,
        w.new_videos_current_views_sum,
        w.new_comments_count,

        w.cumulative_reviews_count,
        w.cumulative_videos_count,
        w.prev_month_reviews_count,
        CASE
            WHEN w.prev_month_reviews_count IS NOT NULL
                THEN w.new_reviews_count - w.prev_month_reviews_count
        END                                                         AS mom_reviews_delta,
        CASE
            WHEN w.prev_month_reviews_count > 0
                THEN ROUND(
                    (w.new_reviews_count - w.prev_month_reviews_count) * 100.0
                    / w.prev_month_reviews_count,
                    2
                )
        END                                                         AS mom_reviews_growth_pct,
        w.rolling_3m_reviews_avg

    FROM with_window_metrics AS w
    LEFT JOIN {{ ref('silver_places') }} AS p
        ON w.place_id = p.place_id
    LEFT JOIN primary_category AS pc
        ON w.place_id = pc.place_id

)

SELECT *
FROM enriched
