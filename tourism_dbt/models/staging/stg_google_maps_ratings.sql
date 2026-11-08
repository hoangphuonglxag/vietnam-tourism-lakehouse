{{ config(materialized='view') }}


WITH bronze AS (

    SELECT *
    FROM {{ source('bronze', 'google_maps_ratings') }}

),

renamed AS (

    SELECT
        -- Thông tin địa điểm
        {{ clean_null('place_id') }}                        AS place_id,
        {{ clean_null('place_name') }}                      AS place_name,
        {{ normalize_province_id('province_id') }}          AS province_id,
        {{ clean_null('province_id') }}                     AS province_id_raw,
        {{ clean_null('province_name') }}                   AS province_name,
        {{ clean_null('google_maps_url') }}                 AS google_maps_url,

        -- Chỉ số rating
        {{ to_double('google_rating') }}                    AS google_rating,
        {{ to_int('google_review_count') }}                 AS google_review_count,
        {{ to_int('rating_5_count') }}                      AS rating_5_count,
        {{ to_int('rating_4_count') }}                      AS rating_4_count,
        {{ to_int('rating_3_count') }}                      AS rating_3_count,
        {{ to_int('rating_2_count') }}                      AS rating_2_count,
        {{ to_int('rating_1_count') }}                      AS rating_1_count,

        -- Trạng thái crawl
        UPPER({{ clean_null('crawl_status') }})             AS crawl_status,
        {{ clean_null('error_message') }}                   AS error_message,

        -- Thời gian
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
