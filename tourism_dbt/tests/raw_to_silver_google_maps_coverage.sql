WITH raw_data AS (
    SELECT COUNT(DISTINCT review_id) AS raw_distinct_reviews
    FROM read_parquet('s3://warehouse/raw/travel_reviews/*.parquet')
),

silver_data AS (

    SELECT COUNT(DISTINCT review_id) AS silver_reviews
    FROM {{ ref('silver_travel_reviews') }}
),

coverage AS (
    SELECT raw_distinct_reviews, silver_reviews,
        CASE
            WHEN raw_distinct_reviews = 0
                THEN 0

            ELSE
                silver_reviews * 1.0
                / raw_distinct_reviews

        END AS coverage_ratio

    FROM raw_data

    CROSS JOIN silver_data
)

SELECT *
FROM coverage
WHERE coverage_ratio < 0.95