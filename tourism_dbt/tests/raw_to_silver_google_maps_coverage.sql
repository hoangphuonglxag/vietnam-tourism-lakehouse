/*
    COVERAGE TEST: Bronze (staging) -> Silver cho Google Maps reviews.
    Tỷ lệ review_id distinct ở Silver / review_id distinct ở Bronze phải >= var('min_bronze_to_silver_ratio').
    Trước đây test đọc trực tiếp đường dẫn parquet cố định; nay dùng ref() để có lineage trong dbt docs
    và luôn đọc cùng nguồn với model.
    Trả về 1 dòng (test FAIL) khi coverage thấp hơn ngưỡng.
*/

WITH raw_data AS (
    SELECT COUNT(DISTINCT review_id) AS raw_distinct_reviews
    FROM {{ ref('stg_google_maps_reviews') }}
),

silver_data AS (
    SELECT COUNT(DISTINCT review_id) AS silver_reviews
    FROM {{ ref('silver_travel_reviews') }}
),

coverage AS (
    SELECT
        raw_distinct_reviews,
        silver_reviews,
        CASE
            WHEN raw_distinct_reviews = 0 THEN 0
            ELSE silver_reviews * 1.0 / raw_distinct_reviews
        END AS coverage_ratio
    FROM raw_data
    CROSS JOIN silver_data
)

SELECT *
FROM coverage
WHERE coverage_ratio < {{ var('min_bronze_to_silver_ratio', 0.95) }}
