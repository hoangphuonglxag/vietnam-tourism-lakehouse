WITH expected_months AS (

    SELECT DATE_TRUNC('month', month_date) AS month
    FROM generate_series(
        DATE '2026-01-01',
        DATE '2026-09-01',
        INTERVAL '1 month'
    ) AS t(month_date)

),


actual_months AS (
    SELECT DISTINCT DATE_TRUNC('month', review_date) AS month
    FROM {{ ref('silver_travel_reviews') }}
    WHERE review_date IS NOT NULL
),

missing_months AS (
    SELECT e.month
    FROM expected_months e
    LEFT JOIN actual_months a
        ON e.month = a.month
    WHERE a.month IS NULL

)
SELECT *
FROM missing_months