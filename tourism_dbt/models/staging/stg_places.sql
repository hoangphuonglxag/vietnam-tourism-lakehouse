{{ config(materialized='view') }}

WITH raw_files AS (

    SELECT
        filename,
        content
    FROM {{ source('bronze', 'places') }}

),

raw_lines AS (

    SELECT
        filename,
        UNNEST(STRING_SPLIT(content, CHR(10))) AS line
    FROM raw_files

),

parsed AS (

    SELECT
        filename,
        REGEXP_EXTRACT(filename, 'crawl_date=([0-9]{4}-[0-9]{2}-[0-9]{2})', 1) AS crawl_date,
        CAST(
            REGEXP_REPLACE(line, ':\s*(NaN|-?Infinity)\s*([,}])', ': null\2', 'g')
            AS JSON
        ) AS j
    FROM raw_lines
    WHERE TRIM(line) <> ''

),

renamed AS (

    SELECT
        -- Định danh
        {{ clean_null("json_extract_string(j, '$.place_id')") }}               AS place_id,
        {{ clean_null("json_extract_string(j, '$.place_name')") }}             AS place_name,
        {{ clean_null("json_extract_string(j, '$.name_vi')") }}                AS name_vi,
        {{ clean_null("json_extract_string(j, '$.name_en')") }}                AS name_en,

        -- Hành chính
        {{ normalize_province_id("json_extract_string(j, '$.province_id')") }}          AS province_id,
        {{ clean_null("json_extract_string(j, '$.province_id')") }}                     AS province_id_raw,
        {{ clean_null("json_extract_string(j, '$.province_name')") }}                   AS province_name,
        {{ normalize_province_id("json_extract_string(j, '$.current_province_id')") }}  AS current_province_id,
        {{ clean_null("json_extract_string(j, '$.current_province_name')") }}           AS current_province_name,
        {{ normalize_province_id("json_extract_string(j, '$.legacy_province_id')") }}   AS legacy_province_id,
        {{ clean_null("json_extract_string(j, '$.legacy_province_name')") }}            AS legacy_province_name,
        LOWER({{ clean_null("json_extract_string(j, '$.admin_scope')") }})              AS admin_scope,

        -- Vị trí
        {{ to_double("json_extract_string(j, '$.latitude')") }}                AS latitude,
        {{ to_double("json_extract_string(j, '$.longitude')") }}               AS longitude,

        -- OpenStreetMap
        LOWER({{ clean_null("json_extract_string(j, '$.osm_type')") }})        AS osm_type,
        {{ clean_null("json_extract_string(j, '$.osm_id')") }}                 AS osm_id,
        {{ clean_null("json_extract_string(j, '$.tourism')") }}                AS osm_tourism_tag,
        {{ clean_null("json_extract_string(j, '$.natural')") }}                AS osm_natural_tag,
        {{ clean_null("json_extract_string(j, '$.historic')") }}               AS osm_historic_tag,
        {{ clean_null("json_extract_string(j, '$.leisure')") }}                AS osm_leisure_tag,

        -- Phân loại / đủ điều kiện crawl
        LOWER({{ clean_null("json_extract_string(j, '$.validation_status')") }})   AS validation_status,
        LOWER({{ clean_null("json_extract_string(j, '$.tourism_status')") }})      AS tourism_status,
        {{ clean_null("json_extract_string(j, '$.tourism_reason')") }}             AS tourism_reason,
        LOWER({{ clean_null("json_extract_string(j, '$.tourism_confidence')") }})  AS tourism_confidence,
        {{ to_bool("json_extract_string(j, '$.crawl_eligible')") }}                AS crawl_eligible,
        {{ to_utc_timestamp("json_extract_string(j, '$.classified_at_utc')") }}    AS classified_at_utc,

        -- Metadata Bronze (lineage)
        {{ clean_null("json_extract_string(j, '$.run_id')") }}                 AS bronze_run_id,
        {{ to_utc_timestamp("json_extract_string(j, '$.ingested_at_utc')") }}  AS bronze_ingested_at_utc,
        LOWER({{ clean_null("json_extract_string(j, '$.record_status')") }})   AS bronze_record_status,
        TRY_CAST(crawl_date AS DATE)                                           AS bronze_crawl_date,
        filename                                                               AS bronze_file_path

    FROM parsed

)

SELECT *
FROM renamed
