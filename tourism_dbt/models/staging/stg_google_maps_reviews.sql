{{ config(materialized='view') }}

WITH bronze AS (

    SELECT *
    FROM {{ source('bronze', 'google_maps_reviews') }}

),

renamed AS (

    SELECT
        -- Khóa định danh
        {{ clean_null('review_id') }}                       AS review_id,
        {{ clean_null('place_id') }}                        AS place_id,

        -- Nội dung review
        {{ to_int('rating') }}                              AS rating,
        {{ clean_text('review_text') }}                     AS review_text,
        LOWER({{ clean_null('review_date') }})              AS review_date_raw,
        {{ to_int('likes_count') }}                         AS likes_count,
        LOWER({{ clean_null('source') }})                   AS source,

        -- Thời gian
        {{ to_utc_timestamp('crawled_at_utc') }}            AS crawled_at_utc,

        -- Metadata Bronze (lineage)
        {{ clean_null('run_id') }}                          AS bronze_run_id,
        {{ to_utc_timestamp('ingested_at_utc') }}           AS bronze_ingested_at_utc,
        LOWER({{ clean_null('record_status') }})            AS bronze_record_status,
        TRY_CAST(crawl_date AS DATE)                        AS bronze_crawl_date,
        filename                                            AS bronze_file_path

    FROM bronze

)

SELECT *
FROM renamed