{{ config(materialized='table') }}


WITH deduplicated AS (
    {{ deduplicate_reviews(
        ref('stg_google_maps_reviews'),
        'review_id'
    ) }}
),
cleaned AS (
    SELECT
        review_id,
        place_id,
        review_text,
        CASE
            WHEN rating BETWEEN 1 AND 5
                THEN rating
            ELSE NULL
        END AS rating,

        review_date_raw,

        CAST(
            {{ normalize_relative_date(
                'review_date_raw',
                'CAST(crawled_at_utc AS DATE)'
            ) }}
            AS DATE
        ) AS review_date,

        CASE

            WHEN review_date_raw LIKE '%ngày trước'
                THEN 'day'

            WHEN review_date_raw LIKE '%tuần trước'
                THEN 'week'

            WHEN review_date_raw LIKE '%tháng trước'
                THEN 'month'

            WHEN review_date_raw LIKE '%năm trước'
                THEN 'year'

            ELSE 'unknown'

        END AS review_date_precision,

        CASE
            WHEN likes_count >= 0
                THEN likes_count
            ELSE NULL
        END AS likes_count,

        LOWER(
            TRIM(source)
        ) AS source,

        crawled_at_utc

    FROM deduplicated
)

SELECT
    review_id,
    place_id,
    rating,
    review_text,
    review_date_raw,
    review_date,
    review_date_precision,
    likes_count,
    source,
    crawled_at_utc
FROM cleaned