{{ config(materialized='table') }}


WITH deduplicated AS (
    {{ deduplicate_reviews(
        ref('stg_youtube_comments'),
        'comment_id'
    ) }}
),

cleaned AS (

    SELECT
        place_id,
        place_name,
        province_id,
        province_name,
        video_id,
        video_title,

        -- COMMENT
        comment_id,
        author,
        comment_text,

        CASE
            WHEN likes >= 0
                THEN likes
            ELSE NULL
        END AS likes,

        COALESCE(
            is_reply,
            FALSE
        ) AS is_reply,

        CAST(
            comment_created_at AS TIMESTAMP
        ) AS comment_created_at,

        CAST(
            crawled_at_utc AS TIMESTAMP
        ) AS crawled_at_utc

    FROM deduplicated

)

SELECT
    place_id,
    place_name,
    province_id,
    province_name,
    video_id,
    video_title,
    comment_id,
    author,
    comment_text,
    likes,
    is_reply,
    comment_created_at,
    crawled_at_utc,
    'youtube' AS source

FROM cleaned