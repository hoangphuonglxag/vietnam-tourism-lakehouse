{{ config(materialized='view') }}

WITH bronze AS (

    SELECT *
    FROM {{ source('bronze', 'provinces') }}

),

renamed AS (

    SELECT
        -- Định danh tỉnh
        {{ normalize_province_id('province_id') }}          AS province_id,
        {{ clean_null('province_id') }}                     AS province_id_raw,
        {{ clean_null('province_name') }}                   AS province_name,

        -- Khung bao địa lý (bounding box)
        {{ to_double('min_lon') }}                          AS min_lon,
        {{ to_double('min_lat') }}                          AS min_lat,
        {{ to_double('max_lon') }}                          AS max_lon,
        {{ to_double('max_lat') }}                          AS max_lat,
        {{ clean_null('geojson_url') }}                     AS geojson_url,

        -- Phạm vi & phiên bản bộ tỉnh
        LOWER({{ clean_null('admin_scope') }})              AS admin_scope,
        {{ clean_null('province_set_version') }}            AS province_set_version,
        {{ to_utc_timestamp('fetched_at_utc') }}            AS fetched_at_utc,

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

