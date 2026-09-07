{{ config(
    materialized='table'
) }}

SELECT
    place_id,
    place_name,
    CAST(rating AS DOUBLE) AS rating,
    LOWER(review_text) AS review_text_cleaned,
    source
FROM read_parquet(
    's3://warehouse/raw/travel_reviews/*.parquet'
)
WHERE rating IS NOT NULL