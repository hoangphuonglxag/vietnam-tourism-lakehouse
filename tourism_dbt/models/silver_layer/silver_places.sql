{{ config(materialized='table') }}

WITH valid_records AS (

    -- BƯỚC 1: dữ liệu thiếu khóa / bị quarantine bị loại
    SELECT *
    FROM {{ ref('stg_places') }}
    WHERE place_id IS NOT NULL
      AND place_name IS NOT NULL
      AND COALESCE(bronze_record_status, 'success') = 'success'

),

snapshot_bounds AS (

    -- BƯỚC 2: vòng đời của place qua các snapshot
    SELECT
        place_id,
        MIN(bronze_crawl_date)              AS first_seen_crawl_date,
        MAX(bronze_crawl_date)              AS last_seen_crawl_date,
        COUNT(DISTINCT bronze_crawl_date)   AS snapshot_count
    FROM valid_records
    GROUP BY place_id

),

latest_snapshot AS (

    SELECT MAX(bronze_crawl_date) AS latest_crawl_date
    FROM valid_records

),

deduplicated AS (

    -- BƯỚC 3: giữ bản ghi mới nhất của mỗi place_id
    {{ deduplicate_by_key(
        'valid_records',
        'place_id',
        'bronze_crawl_date DESC NULLS LAST, bronze_ingested_at_utc DESC NULLS LAST'
    ) }}

),

standardized AS (

    -- BƯỚC 4: kiểm tra miền giá trị & giá trị mặc định
    SELECT
        d.place_id,
        d.place_name,
        d.name_vi,
        d.name_en,

        d.province_id,
        COALESCE(prov.province_name, d.province_name)           AS province_name,
        (prov.province_id IS NOT NULL)                          AS is_province_in_dim,
        d.current_province_id,
        d.current_province_name,
        d.legacy_province_id,
        d.legacy_province_name,
        d.admin_scope,

        CASE WHEN d.latitude  BETWEEN -90  AND 90  THEN d.latitude  END AS latitude,
        CASE WHEN d.longitude BETWEEN -180 AND 180 THEN d.longitude END AS longitude,

        d.osm_type,
        d.osm_id,
        d.osm_tourism_tag,
        d.osm_natural_tag,
        d.osm_historic_tag,
        d.osm_leisure_tag,

        d.validation_status,
        d.tourism_status,
        d.tourism_reason,
        d.tourism_confidence,
        COALESCE(d.crawl_eligible, FALSE)                       AS crawl_eligible,
        d.classified_at_utc,

        b.first_seen_crawl_date,
        b.last_seen_crawl_date,
        b.snapshot_count,
        (b.last_seen_crawl_date = s.latest_crawl_date)          AS is_in_latest_snapshot,

        d.bronze_run_id,
        d.bronze_ingested_at_utc

    FROM deduplicated AS d
    INNER JOIN snapshot_bounds AS b
        ON d.place_id = b.place_id
    LEFT JOIN {{ ref('silver_provinces') }} AS prov
        ON d.province_id = prov.province_id
    CROSS JOIN latest_snapshot AS s

)

SELECT *
FROM standardized
