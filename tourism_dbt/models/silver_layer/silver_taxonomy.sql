{{ config(materialized='table') }}

WITH valid_records AS (

    -- BƯỚC 1: loại bản ghi thiếu khóa / nhóm bắt buộc (theo data contract mục 4.2)
    SELECT *
    FROM {{ ref('stg_taxonomy') }}
    WHERE category_id IS NOT NULL
      AND category_group IS NOT NULL
      AND category_name IS NOT NULL
      AND COALESCE(bronze_record_status, 'success') = 'success'

),

snapshot_bounds AS (

    -- BƯỚC 2: vòng đời qua các snapshot
    SELECT
        category_id,
        MIN(bronze_crawl_date)              AS first_seen_crawl_date,
        MAX(bronze_crawl_date)              AS last_seen_crawl_date,
        COUNT(DISTINCT bronze_crawl_date)   AS snapshot_count
    FROM valid_records
    GROUP BY category_id

),

deduplicated AS (

    -- BƯỚC 3: giữ bản ghi ở snapshot mới nhất
    {{ deduplicate_by_key(
        'valid_records',
        'category_id',
        'bronze_crawl_date DESC NULLS LAST, bronze_ingested_at_utc DESC NULLS LAST'
    ) }}

),

standardized AS (

    SELECT
        d.category_id,
        d.category_group,
        d.category_name,
        d.subcategory_name,
        d.name_vi,
        d.name_en,

        b.first_seen_crawl_date,
        b.last_seen_crawl_date,
        b.snapshot_count,

        d.bronze_run_id,
        d.bronze_ingested_at_utc

    FROM deduplicated AS d
    INNER JOIN snapshot_bounds AS b
        ON d.category_id = b.category_id

)

SELECT *
FROM standardized

