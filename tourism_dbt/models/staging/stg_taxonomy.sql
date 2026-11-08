{{ config(materialized='view') }}

WITH bronze AS (

    SELECT *
    FROM {{ source('bronze', 'taxonomy') }}

),

renamed AS (

    SELECT
        -- Định danh & cây phân loại
        UPPER({{ clean_null('category_id') }})              AS category_id,
        LOWER({{ clean_null('"group"') }})                  AS category_group,
        LOWER({{ clean_null('category') }})                 AS category_name,
        LOWER({{ clean_null('subcategory') }})              AS subcategory_name,
        {{ clean_null('name_vi') }}                         AS name_vi,
        {{ clean_null('name_en') }}                         AS name_en,

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

