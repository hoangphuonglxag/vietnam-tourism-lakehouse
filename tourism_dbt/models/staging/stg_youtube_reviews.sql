{{ config(materialized='view') }}

SELECT
    -- PLACE INFORMATION
    {{ clean_null('place_id') }} AS place_id,

    {{ clean_null('place_name') }} AS place_name,

    {{ clean_null('province_id') }} AS province_id,

    {{ clean_null('province_name') }} AS province_name,

    -- VIDEO INFORMATION
    {{ clean_null('video_id') }} AS video_id,

    {{ clean_text('video_title') }} AS video_title,

    -- COMMENT INFORMATION
    {{ clean_null('comment_id') }} AS comment_id,

    {{ clean_null('author') }} AS author,

    {{ clean_text('text') }} AS comment_text,

    CAST(likes AS INTEGER) AS likes,

    CAST(is_reply AS BOOLEAN) AS is_reply,

    -- TIME INFORMATION
    CAST(comment_created_at AS TIMESTAMPTZ) AS comment_created_at,

    CAST(crawled_at_utc AS TIMESTAMPTZ) AS crawled_at_utc

FROM read_parquet(
    's3://warehouse/raw/youtube_comments/*.parquet'
)