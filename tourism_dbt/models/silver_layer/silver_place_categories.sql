{{ config(materialized='table') }}


WITH valid_records AS (

    -- BƯỚC 1: loại bản ghi thiếu khóa / quarantine
    SELECT *
    FROM {{ ref('stg_place_categories') }}
    WHERE place_id IS NOT NULL
      AND category_id IS NOT NULL
      AND COALESCE(bronze_record_status, 'success') = 'success'

),

deduplicated AS (

    -- BƯỚC 2: khử trùng lặp theo (place_id, category_id)
    {{ deduplicate_by_key(
        'valid_records',
        ['place_id', 'category_id'],
        'bronze_crawl_date DESC NULLS LAST, bronze_ingested_at_utc DESC NULLS LAST, is_primary DESC NULLS LAST'
    ) }}

),

cleaned AS (

    -- BƯỚC 3: kiểm tra miền giá trị
    SELECT
        place_id || '|' || category_id                          AS place_category_id,
        place_id,
        category_id,
        category_group,
        category_name,
        subcategory_name,
        COALESCE(is_primary, FALSE)                             AS is_primary,
        classification_method,
        CASE
            WHEN classification_confidence IN ('high', 'medium', 'low')
                THEN classification_confidence
        END                                                     AS classification_confidence,
        bronze_crawl_date,
        bronze_run_id,
        bronze_ingested_at_utc
    FROM deduplicated

),

enriched AS (

    -- BƯỚC 4: chuẩn hóa theo silver_taxonomy và silver_places (LEFT JOIN, không làm đổi số dòng)
    SELECT
        c.place_category_id,
        c.place_id,
        p.place_name,
        p.province_id,
        p.province_name,
        (p.place_id IS NOT NULL)                                AS is_place_in_dim,

        c.category_id,
        COALESCE(t.category_group, c.category_group)            AS category_group,
        COALESCE(t.category_name, c.category_name)              AS category_name,
        COALESCE(t.subcategory_name, c.subcategory_name)        AS subcategory_name,
        t.name_vi                                               AS category_name_vi,
        t.name_en                                               AS category_name_en,
        (t.category_id IS NOT NULL)                             AS is_category_in_dim,

        c.is_primary,
        c.classification_method,
        c.classification_confidence,

        c.bronze_crawl_date,
        c.bronze_run_id,
        c.bronze_ingested_at_utc

    FROM cleaned AS c
    LEFT JOIN {{ ref('silver_taxonomy') }} AS t
        ON c.category_id = t.category_id
    LEFT JOIN {{ ref('silver_places') }} AS p
        ON c.place_id = p.place_id

)

SELECT *
FROM enriched

