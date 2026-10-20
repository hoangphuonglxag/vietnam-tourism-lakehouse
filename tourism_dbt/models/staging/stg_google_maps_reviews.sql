{{ config(materialized='view') }}

SELECT
    {{ clean_null('review_id') }} AS review_id,

    {{ clean_null('place_id') }} AS place_id,

    CAST(rating AS INTEGER) AS rating,

    {{ clean_text('review_text') }} AS review_text,

    LOWER(
        TRIM(review_date)
    ) AS review_date_raw,

    CAST(likes_count AS INTEGER) AS likes_count,

    LOWER(
        TRIM(source)
    ) AS source,


    CAST(crawled_at_utc AS TIMESTAMPTZ) AS crawled_at_utc

FROM read_parquet(
    's3://warehouse/raw/travel_reviews/*.parquet'
)