{{ config(tags=['gold']) }}

/*
    GOLD TO SILVER RECONCILIATION TEST:
    Kiểm tra bảo toàn số dòng và tổng các chỉ số cốt lõi giữa lớp Gold và lớp Silver:
      1. Số dòng của gold_obt_place_360_profile == số dòng của silver_places.
      2. Số dòng của gold_fct_province_tourism_summary == số dòng của silver_provinces.
      3. Số dòng của gold_fct_category_tourism_summary == số dòng của silver_taxonomy.
      4. Số dòng của gold_fct_youtube_video_performance == số dòng của silver_youtube_videos.
      5. Tổng total_places_count của 34 tỉnh trong gold_fct_province_tourism_summary == số dòng của gold_obt_place_360_profile.
      6. Tổng crawled_review_count và youtube_video_count trong gold_obt_place_360_profile khớp tuyệt đối với silver_place_temporal_coverage.
    Trả về các hạng mục bị lệch (0 dòng = PASS).
*/

WITH checks AS (

    SELECT
        'place_360_row_count'                                                       AS check_name,
        (SELECT COUNT(*) FROM {{ ref('gold_obt_place_360_profile') }})              AS gold_value,
        (SELECT COUNT(*) FROM {{ target.schema }}.silver_places)                    AS expected_value

    UNION ALL

    SELECT
        'province_summary_row_count',
        (SELECT COUNT(*) FROM {{ ref('gold_fct_province_tourism_summary') }}),
        (SELECT COUNT(*) FROM {{ target.schema }}.silver_provinces)

    UNION ALL

    SELECT
        'category_summary_row_count',
        (SELECT COUNT(*) FROM {{ ref('gold_fct_category_tourism_summary') }}),
        (SELECT COUNT(*) FROM {{ target.schema }}.silver_taxonomy)

    UNION ALL

    SELECT
        'video_performance_row_count',
        (SELECT COUNT(*) FROM {{ ref('gold_fct_youtube_video_performance') }}),
        (SELECT COUNT(*) FROM {{ target.schema }}.silver_youtube_videos)

    UNION ALL

    SELECT
        'province_places_sum_matches_place_360',
        (SELECT COALESCE(SUM(total_places_count), 0) FROM {{ ref('gold_fct_province_tourism_summary') }}),
        (SELECT COUNT(*) FROM {{ ref('gold_obt_place_360_profile') }})

    UNION ALL

    SELECT
        'place_360_reviews_matches_coverage',
        (SELECT COALESCE(SUM(crawled_review_count), 0) FROM {{ ref('gold_obt_place_360_profile') }}),
        (SELECT COALESCE(SUM(review_count), 0) FROM {{ target.schema }}.silver_place_temporal_coverage)

    UNION ALL

    SELECT
        'place_360_videos_matches_coverage',
        (SELECT COALESCE(SUM(youtube_video_count), 0) FROM {{ ref('gold_obt_place_360_profile') }}),
        (SELECT COALESCE(SUM(video_count), 0) FROM {{ target.schema }}.silver_place_temporal_coverage)

)

SELECT *
FROM checks
WHERE COALESCE(gold_value, -1) <> COALESCE(expected_value, -2)
