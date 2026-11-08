{{ config(materialized='table') }}

WITH valid_records AS (

    -- BƯỚC 1: loại bản ghi thiếu khóa / quarantine
    SELECT *
    FROM {{ ref('stg_google_maps_reviews') }}
    WHERE review_id IS NOT NULL
      AND place_id IS NOT NULL
      AND crawled_at_utc IS NOT NULL
      AND COALESCE(bronze_record_status, 'success') = 'success'

),

parsed AS (

    -- BƯỚC 2: ngày tương đối -> ngày ước lượng, mốc tham chiếu là ngày crawl (UTC)
    SELECT
        *,
        {{ normalize_relative_date('review_date_raw', 'CAST(crawled_at_utc AS DATE)') }}
            AS review_date_estimated,
        {{ relative_date_precision('review_date_raw') }}
            AS review_date_precision_estimated,
        COALESCE(REGEXP_MATCHES(review_date_raw, 'chỉnh sửa|edited'), FALSE)
            AS is_edited_observation
    FROM valid_records

),

ranked AS (

    SELECT
        *,
        CASE review_date_precision_estimated
            WHEN 'day'   THEN 1
            WHEN 'week'  THEN 2
            WHEN 'month' THEN 3
            WHEN 'year'  THEN 4
            ELSE 5
        END AS precision_rank
    FROM parsed

),

observation_stats AS (

    -- BƯỚC 3
    SELECT
        review_id,
        COUNT(*)                AS observation_count,
        MIN(crawled_at_utc)     AS first_crawled_at_utc
    FROM ranked
    GROUP BY review_id

),

latest_observation AS (

    -- BƯỚC 4: khử trùng lặp, giữ lần crawl mới nhất
    {{ deduplicate_by_key(
        'ranked',
        'review_id',
        'crawled_at_utc DESC, bronze_ingested_at_utc DESC NULLS LAST'
    ) }}

),

best_date_observation AS (

    -- BƯỚC 5: quan sát có độ chính xác ngày tốt nhất (day > week > month > year),
    -- nếu bằng nhau thì lấy lần crawl sớm nhất
    SELECT
        review_id,
        review_date_raw         AS best_review_date_raw,
        review_date_estimated   AS best_review_date,
        review_date_precision_estimated AS best_review_date_precision
    FROM ranked
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY review_id
        ORDER BY precision_rank ASC, crawled_at_utc ASC
    ) = 1

),

cleaned AS (

    -- BƯỚC 6: kiểm tra miền giá trị
    SELECT
        l.review_id,
        l.place_id,

        CASE WHEN l.rating BETWEEN 1 AND 5 THEN l.rating END           AS rating,
        l.review_text,
        (l.review_text IS NOT NULL)                                     AS has_review_text,

        b.best_review_date_raw                                          AS review_date_raw,
        b.best_review_date                                              AS review_date,
        b.best_review_date_precision                                    AS review_date_precision,
        CAST(DATE_TRUNC('month', b.best_review_date) AS DATE)           AS review_month,
        l.is_edited_observation                                         AS is_edited,

        CASE WHEN l.likes_count >= 0 THEN l.likes_count END             AS likes_count,
        COALESCE(l.source, 'google_maps')                               AS source,

        l.crawled_at_utc,
        o.first_crawled_at_utc,
        o.observation_count,
        l.bronze_run_id

    FROM latest_observation AS l
    INNER JOIN best_date_observation AS b
        ON l.review_id = b.review_id
    INNER JOIN observation_stats AS o
        ON l.review_id = o.review_id

),

enriched AS (

    -- BƯỚC 7: chuẩn hóa place/province theo dimension (LEFT JOIN, place_id unique ở dim)
    SELECT
        c.review_id,
        c.place_id,
        p.place_name,
        p.province_id,
        p.province_name,
        (p.place_id IS NOT NULL)        AS is_place_in_dim,

        c.rating,
        c.review_text,
        c.has_review_text,
        c.review_date_raw,
        c.review_date,
        c.review_date_precision,
        c.review_month,
        c.is_edited,
        c.likes_count,
        c.source,

        c.crawled_at_utc,
        c.first_crawled_at_utc,
        c.observation_count,
        c.bronze_run_id

    FROM cleaned AS c
    LEFT JOIN {{ ref('silver_places') }} AS p
        ON c.place_id = p.place_id

)

SELECT *
FROM enriched