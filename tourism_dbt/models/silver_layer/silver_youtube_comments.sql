{{ config(materialized='table') }}

WITH valid_records AS (

    -- BƯỚC 1
    SELECT
        *,
        COALESCE(
            comment_id,
            'sk_' || MD5(CONCAT_WS('||', video_id, COALESCE(author, ''), COALESCE(comment_text, '')))
        )                               AS comment_key,
        (comment_id IS NULL)            AS is_surrogate_comment_key
    FROM {{ ref('stg_youtube_comments') }}
    WHERE place_id IS NOT NULL
      AND video_id IS NOT NULL
      AND crawled_at_utc IS NOT NULL
      AND (comment_id IS NOT NULL OR comment_text IS NOT NULL)
      AND COALESCE(bronze_record_status, 'success') = 'success'

),

observation_stats AS (

    -- BƯỚC 2
    SELECT
        place_id,
        comment_key,
        COUNT(*)                AS observation_count,
        MIN(crawled_at_utc)     AS first_crawled_at_utc
    FROM valid_records
    GROUP BY place_id, comment_key

),

deduplicated AS (

    -- BƯỚC 3
    {{ deduplicate_by_key(
        'valid_records',
        ['place_id', 'comment_key'],
        'crawled_at_utc DESC, bronze_ingested_at_utc DESC NULLS LAST'
    ) }}

),

parsed_created_at AS (

    -- BƯỚC 4
    SELECT
        *,
        {{ to_utc_timestamp('comment_created_at_raw') }}
            AS created_at_exact,
        CAST(
            {{ normalize_relative_date('comment_created_at_raw', 'CAST(crawled_at_utc AS DATE)') }}
            AS TIMESTAMP
        )   AS created_at_relative,
        {{ relative_date_precision('comment_created_at_raw') }}
            AS created_at_relative_precision
    FROM deduplicated

),

cleaned AS (

    -- BƯỚC 5
    SELECT
        d.*,
        CASE
            WHEN COALESCE(d.created_at_exact, d.created_at_relative) > d.crawled_at_utc + INTERVAL 1 DAY
                THEN NULL
            ELSE COALESCE(d.created_at_exact, d.created_at_relative)
        END AS comment_created_at_utc_checked,
        CASE
            WHEN d.created_at_exact IS NOT NULL THEN 'exact'
            ELSE d.created_at_relative_precision
        END AS comment_created_at_precision_checked
    FROM parsed_created_at AS d

),

enriched AS (

    -- BƯỚC 6
    SELECT
        c.place_id,
        COALESCE(p.place_name, c.place_name)            AS place_name,
        COALESCE(p.province_id, c.province_id)          AS province_id,
        COALESCE(p.province_name, c.province_name)      AS province_name,
        (p.place_id IS NOT NULL)                        AS is_place_in_dim,

        c.video_id,
        c.video_title,

        c.comment_key,
        c.comment_id,
        c.is_surrogate_comment_key,
        c.author,
        c.comment_text,
        CASE WHEN c.likes >= 0 THEN c.likes END         AS likes,
        COALESCE(c.is_reply, FALSE)                     AS is_reply,

        c.comment_created_at_raw,
        c.comment_created_at_utc_checked                AS comment_created_at_utc,
        CASE
            WHEN c.comment_created_at_utc_checked IS NULL THEN 'unknown'
            ELSE c.comment_created_at_precision_checked
        END                                             AS comment_created_at_precision,
        CAST(c.comment_created_at_utc_checked AS DATE)  AS comment_created_date,

        c.crawled_at_utc,
        o.first_crawled_at_utc,
        o.observation_count,
        'youtube'                                       AS source,
        c.bronze_run_id

    FROM cleaned AS c
    INNER JOIN observation_stats AS o
        ON  c.place_id = o.place_id
        AND c.comment_key = o.comment_key
    LEFT JOIN {{ ref('silver_places') }} AS p
        ON c.place_id = p.place_id

)

SELECT *
FROM enriched