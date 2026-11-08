{{ config(materialized='view') }}

WITH bronze AS (

    SELECT *
    FROM {{ source('bronze', 'place_categories') }}

),

renamed AS (

    SELECT
        -- Khóa ánh xạ
        {{ clean_null('place_id') }}                        AS place_id,
        UPPER({{ clean_null('category_id') }})              AS category_id,

        -- Thông tin phân loại đi kèm ở nguồn
        LOWER({{ clean_null('"group"') }})                  AS category_group,
        LOWER({{ clean_null('category') }})                 AS category_name,
        LOWER({{ clean_null('subcategory') }})              AS subcategory_name,
        {{ to_bool('is_primary') }}                         AS is_primary,
        LOWER({{ clean_null('classification_method') }})    AS classification_method,
        LOWER({{ clean_null('classification_confidence') }}) AS classification_confidence,

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

