{{ config(materialized='view') }}

WITH bronze AS (

    SELECT *
    FROM {{ source('bronze', 'youtube_comments') }}

),

renamed AS (

    SELECT
        -- Thông tin địa điểm
        {{ clean_null('place_id') }}                        AS place_id,
        {{ clean_null('place_name') }}                      AS place_name,
        {{ normalize_province_id('province_id') }}          AS province_id,
        {{ clean_null('province_id') }}                     AS province_id_raw,
        {{ clean_null('province_name') }}                   AS province_name,

        -- Thông tin video
        {{ clean_null('video_id') }}                        AS video_id,
        {{ clean_text('video_title') }}                     AS video_title,

        -- Thông tin comment
        {{ clean_null('comment_id') }}                      AS comment_id,
        {{ clean_null('author') }}                          AS author,
        {{ clean_text('"text"') }}                          AS comment_text,
        {{ to_int('likes') }}                               AS likes,
        {{ to_bool('is_reply') }}                           AS is_reply,

        -- Thời gian
        {{ clean_null('comment_created_at') }}              AS comment_created_at_raw,
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