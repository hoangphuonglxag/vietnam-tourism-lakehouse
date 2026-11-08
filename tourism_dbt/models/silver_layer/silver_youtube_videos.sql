{{ config(materialized='table') }}

WITH valid_records AS (

    -- BƯỚC 1
    SELECT *
    FROM {{ ref('stg_youtube_videos') }}
    WHERE place_id IS NOT NULL
      AND video_id IS NOT NULL
      AND crawled_at_utc IS NOT NULL
      AND COALESCE(bronze_record_status, 'success') = 'success'

),

observation_stats AS (

    -- BƯỚC 2
    SELECT
        place_id,
        video_id,
        COUNT(*)                AS observation_count,
        MIN(crawled_at_utc)     AS first_crawled_at_utc
    FROM valid_records
    GROUP BY place_id, video_id

),

deduplicated AS (

    -- BƯỚC 3
    {{ deduplicate_by_key(
        'valid_records',
        ['place_id', 'video_id'],
        'crawled_at_utc DESC, bronze_ingested_at_utc DESC NULLS LAST'
    ) }}

),

cleaned AS (

    -- BƯỚC 4
    SELECT
        d.*,
        CASE
            WHEN d.published_at_utc > d.crawled_at_utc + INTERVAL 1 DAY THEN NULL
            ELSE d.published_at_utc
        END                                                         AS published_at_utc_checked,
        CASE WHEN d.views >= 0 THEN d.views END                     AS views_checked,
        CASE WHEN d.duration_seconds >= 0 THEN d.duration_seconds END AS duration_seconds_checked
    FROM deduplicated AS d

),

enriched AS (

    -- BƯỚC 5
    SELECT
        c.place_id,
        COALESCE(p.place_name, c.place_name)                AS place_name,
        COALESCE(p.province_id, c.province_id)              AS province_id,
        COALESCE(p.province_name, c.province_name)          AS province_name,
        (p.place_id IS NOT NULL)                            AS is_place_in_dim,

        c.video_id,
        c.video_title,
        c.channel_id,
        c.channel_name,
        c.search_query,
        c.views_checked                                     AS views,
        c.duration_seconds_checked                          AS duration_seconds,
        c.category,
        c.thumbnail_url,
        c.video_url,

        c.published_at_raw,
        c.published_at_utc_checked                          AS published_at_utc,
        CAST(c.published_at_utc_checked AS DATE)            AS published_date,
        CAST(DATE_TRUNC('month', c.published_at_utc_checked) AS DATE) AS published_month,

        c.crawled_at_utc,
        o.first_crawled_at_utc,
        o.observation_count,
        'youtube'                                           AS source,
        c.bronze_run_id

    FROM cleaned AS c
    INNER JOIN observation_stats AS o
        ON  c.place_id = o.place_id
        AND c.video_id = o.video_id
    LEFT JOIN {{ ref('silver_places') }} AS p
        ON c.place_id = p.place_id

)

SELECT *
FROM enriched
