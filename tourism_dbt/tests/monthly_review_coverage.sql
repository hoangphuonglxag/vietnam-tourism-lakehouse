{{ config(severity='warn') }}

/*
    MONTHLY COVERAGE TEST: mỗi tháng trong khoảng
    [var('review_coverage_start_month'), var('review_coverage_end_month')]
    phải có ít nhất 1 review với ngày đủ chính xác (precision day/week/month).
    Trả về các tháng bị thiếu. Severity = warn vì review của dữ liệu crawl
    phụ thuộc vào nguồn, thiếu tháng là cảnh báo chứ không chặn pipeline.
*/

WITH expected_months AS (
    SELECT CAST(DATE_TRUNC('month', month_date) AS DATE) AS month
    FROM generate_series(
        CAST('{{ var("review_coverage_start_month") }}' AS DATE),
        CAST('{{ var("review_coverage_end_month") }}' AS DATE),
        INTERVAL 1 MONTH
    ) AS t(month_date)
),

actual_months AS (
    SELECT DISTINCT review_month AS month
    FROM {{ ref('silver_travel_reviews') }}
    WHERE review_month IS NOT NULL
      AND review_date_precision IN ('day', 'week', 'month')
)

SELECT e.month
FROM expected_months AS e
LEFT JOIN actual_months AS a
    ON e.month = a.month
WHERE a.month IS NULL
