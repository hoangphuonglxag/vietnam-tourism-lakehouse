{{ config(materialized='table') }}

WITH valid_records AS (

    -- BƯỚC 1 + 2
    SELECT
        *,
        CAST(crawled_at_utc AS DATE) AS snapshot_date
    FROM {{ ref('stg_google_maps_ratings') }}
    WHERE place_id IS NOT NULL
      AND crawled_at_utc IS NOT NULL
      AND crawl_status = 'SUCCESS'
      AND COALESCE(bronze_record_status, 'success') = 'success'

),

deduplicated AS (

    -- BƯỚC 3
    {{ deduplicate_by_key(
        'valid_records',
        ['place_id', 'snapshot_date'],
        'crawled_at_utc DESC, bronze_ingested_at_utc DESC NULLS LAST'
    ) }}

),

cleaned AS (

    -- BƯỚC 4
    SELECT
        place_id,
        place_name,
        province_id,
        province_name,
        google_maps_url,
        snapshot_date,
        crawled_at_utc,
        CASE WHEN google_rating BETWEEN 0 AND 5 THEN google_rating END        AS google_rating,
        CASE WHEN google_review_count >= 0 THEN google_review_count END       AS google_review_count,
        CASE WHEN rating_5_count >= 0 THEN rating_5_count END                 AS rating_5_count,
        CASE WHEN rating_4_count >= 0 THEN rating_4_count END                 AS rating_4_count,
        CASE WHEN rating_3_count >= 0 THEN rating_3_count END                 AS rating_3_count,
        CASE WHEN rating_2_count >= 0 THEN rating_2_count END                 AS rating_2_count,
        CASE WHEN rating_1_count >= 0 THEN rating_1_count END                 AS rating_1_count,
        crawl_status,
        bronze_run_id
    FROM deduplicated

),

with_distribution AS (

    SELECT
        *,
        COALESCE(rating_5_count, 0) + COALESCE(rating_4_count, 0) + COALESCE(rating_3_count, 0)
            + COALESCE(rating_2_count, 0) + COALESCE(rating_1_count, 0)    AS rating_distribution_total
    FROM cleaned

),

enriched AS (

    -- BƯỚC 5
    SELECT
        w.place_id || '|' || CAST(w.snapshot_date AS VARCHAR)   AS rating_snapshot_id,
        w.place_id,
        COALESCE(p.place_name, w.place_name)                    AS place_name,
        COALESCE(p.province_id, w.province_id)                  AS province_id,
        COALESCE(p.province_name, w.province_name)              AS province_name,
        (p.place_id IS NOT NULL)                                AS is_place_in_dim,

        w.snapshot_date,
        w.crawled_at_utc,
        w.google_maps_url,

        w.google_rating,
        w.google_review_count,
        w.rating_5_count,
        w.rating_4_count,
        w.rating_3_count,
        w.rating_2_count,
        w.rating_1_count,
        w.rating_distribution_total,
        (w.google_rating IS NOT NULL)                           AS has_rating_value,
        (w.rating_distribution_total > 0)                       AS has_rating_distribution,

        w.crawl_status,
        'google_maps'                                           AS source,
        w.bronze_run_id

    FROM with_distribution AS w
    LEFT JOIN {{ ref('silver_places') }} AS p
        ON w.place_id = p.place_id

)

SELECT *
FROM enriched
