{{ config(materialized='view') }}

WITH bronze AS (

    SELECT *
    FROM {{ source('bronze', 'youtube_videos') }}

),

renamed AS (

    SELECT
        -- Thông tin địa điểm
        {{ clean_null('place_id') }}                        AS place_id,
        {{ clean_null('place_name') }}                      AS place_name,
        {{ normalize_province_id('province_id') }}          AS province_id,
        {{ clean_null('province_id') }}                     AS province_id_raw,
        {{ clean_null('province_name') }}                   AS province_name,
        {{ clean_null('query') }}                           AS search_query,

        -- Thông tin video
        {{ clean_null('video_id') }}                        AS video_id,
        {{ clean_text('title') }}                           AS video_title,
        {{ clean_null('channel_id') }}                      AS channel_id,
        {{ clean_null('channel_name') }}                    AS channel_name,
        {{ to_int('views') }}                               AS views,
        {{ to_int('duration_seconds') }}                    AS duration_seconds,
        {{ clean_null('category') }}                        AS category,
        {{ clean_null('thumbnail') }}                       AS thumbnail_url,
        {{ clean_null('url') }}                             AS video_url,

        -- Thời gian
        {{ clean_null('published_at') }}                    AS published_at_raw,
        {{ to_utc_timestamp('published_at') }}              AS published_at_utc,
        {{ to_utc_timestamp('crawled_at') }}                AS crawled_at_utc,

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
