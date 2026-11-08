{{ config(materialized='table') }}

WITH valid_records AS (

    -- BƯỚC 1: loại bản ghi thiếu khóa / quarantine
    SELECT *
    FROM {{ ref('stg_provinces') }}
    WHERE province_id IS NOT NULL
      AND province_name IS NOT NULL
      AND COALESCE(bronze_record_status, 'success') = 'success'

),

snapshot_bounds AS (

    -- BƯỚC 2: theo dõi vòng đời qua các snapshot
    SELECT
        province_id,
        MIN(bronze_crawl_date)              AS first_seen_crawl_date,
        MAX(bronze_crawl_date)              AS last_seen_crawl_date,
        COUNT(DISTINCT bronze_crawl_date)   AS snapshot_count
    FROM valid_records
    GROUP BY province_id

),

deduplicated AS (

    -- BƯỚC 3: giữ bản ghi ở snapshot mới nhất
    {{ deduplicate_by_key(
        'valid_records',
        'province_id',
        'bronze_crawl_date DESC NULLS LAST, bronze_ingested_at_utc DESC NULLS LAST'
    ) }}

),

standardized AS (

    -- BƯỚC 4: kiểm tra miền tọa độ bounding box & tính tâm
    SELECT
        d.province_id,
        d.province_name,

        CASE
            WHEN d.min_lon BETWEEN -180 AND 180
             AND d.max_lon BETWEEN -180 AND 180
             AND d.min_lon <= d.max_lon
                THEN d.min_lon
        END                                                     AS min_lon,

        CASE
            WHEN d.min_lat BETWEEN -90 AND 90
             AND d.max_lat BETWEEN -90 AND 90
             AND d.min_lat <= d.max_lat
                THEN d.min_lat
        END                                                     AS min_lat,

        CASE
            WHEN d.min_lon BETWEEN -180 AND 180
             AND d.max_lon BETWEEN -180 AND 180
             AND d.min_lon <= d.max_lon
                THEN d.max_lon
        END                                                     AS max_lon,

        CASE
            WHEN d.min_lat BETWEEN -90 AND 90
             AND d.max_lat BETWEEN -90 AND 90
             AND d.min_lat <= d.max_lat
                THEN d.max_lat
        END                                                     AS max_lat,

        CASE
            WHEN d.min_lat BETWEEN -90 AND 90
             AND d.max_lat BETWEEN -90 AND 90
             AND d.min_lat <= d.max_lat
                THEN (d.min_lat + d.max_lat) / 2.0
        END                                                     AS center_lat,

        CASE
            WHEN d.min_lon BETWEEN -180 AND 180
             AND d.max_lon BETWEEN -180 AND 180
             AND d.min_lon <= d.max_lon
                THEN (d.min_lon + d.max_lon) / 2.0
        END                                                     AS center_lon,

        d.geojson_url,
        COALESCE(d.admin_scope, 'current_34')                   AS admin_scope,
        d.province_set_version,
        d.fetched_at_utc,

        b.first_seen_crawl_date,
        b.last_seen_crawl_date,
        b.snapshot_count,

        d.bronze_run_id,
        d.bronze_ingested_at_utc

    FROM deduplicated AS d
    INNER JOIN snapshot_bounds AS b
        ON d.province_id = b.province_id

)

SELECT *
FROM standardized

