{% macro normalize_relative_date(date_column, reference_date) %}

CASE
    -- =========================================================
    -- 1. HOURS
    -- Ví dụ:
    -- 8 giờ trước
    -- =========================================================
    WHEN LOWER(TRIM({{ date_column }})) ~ '^[0-9]+ giờ trước$'
    THEN
        {{ reference_date }}
        - (
            CAST(
                REGEXP_EXTRACT(
                    LOWER(TRIM({{ date_column }})),
                    '[0-9]+'
                ) AS INTEGER
            ) * INTERVAL 1 HOUR
        )

    -- =========================================================
    -- 2. DAYS
    -- Ví dụ:
    -- 1 ngày trước
    -- 3 ngày trước
    -- =========================================================
    WHEN LOWER(TRIM({{ date_column }})) ~ '^[0-9]+ ngày trước$'
    THEN
        {{ reference_date }}
        - (
            CAST(
                REGEXP_EXTRACT(
                    LOWER(TRIM({{ date_column }})),
                    '[0-9]+'
                ) AS INTEGER
            ) * INTERVAL 1 DAY
        )

    WHEN LOWER(TRIM({{ date_column }})) = 'một ngày trước'
    THEN
        {{ reference_date }} - INTERVAL 1 DAY

    WHEN LOWER(TRIM({{ date_column }})) = 'ngày hôm qua'
    THEN
        {{ reference_date }} - INTERVAL 1 DAY

    WHEN LOWER(TRIM({{ date_column }})) = 'hôm nay'
    THEN
        {{ reference_date }}

    -- =========================================================
    -- 3. WEEKS
    -- Ví dụ:
    -- 2 tuần trước
    -- 3 tuần trước
    -- một tuần trước
    -- =========================================================
    WHEN LOWER(TRIM({{ date_column }})) ~ '^[0-9]+ tuần trước$'
    THEN
        {{ reference_date }}
        - (
            CAST(
                REGEXP_EXTRACT(
                    LOWER(TRIM({{ date_column }})),
                    '[0-9]+'
                ) AS INTEGER
            ) * INTERVAL 1 WEEK
        )
    WHEN LOWER(TRIM({{ date_column }})) = 'một tuần trước'
    THEN
        {{ reference_date }} - INTERVAL 1 WEEK

    WHEN LOWER(TRIM({{ date_column }})) = 'tuần trước'
    THEN
        {{ reference_date }} - INTERVAL 1 WEEK

    -- =========================================================
    -- 4. MONTHS
    -- Ví dụ:
    -- một tháng trước
    -- 2 tháng trước
    -- 3 tháng trước
    -- ...
    -- 11 tháng trước
    -- =========================================================
    WHEN LOWER(TRIM({{ date_column }})) ~ '^[0-9]+ tháng trước$'
    THEN
        {{ reference_date }}
        - (
            CAST(
                REGEXP_EXTRACT(
                    LOWER(TRIM({{ date_column }})),
                    '[0-9]+'
                ) AS INTEGER
            ) * INTERVAL 1 MONTH
        )
    WHEN LOWER(TRIM({{ date_column }})) = 'một tháng trước'
    THEN
        {{ reference_date }} - INTERVAL 1 MONTH

    WHEN LOWER(TRIM({{ date_column }})) = 'tháng trước'
    THEN
        {{ reference_date }} - INTERVAL 1 MONTH

    -- =========================================================
    -- 5. YEARS
    -- Ví dụ:
    -- một năm trước
    -- 2 năm trước
    -- 3 năm trước
    -- 4 năm trước
    -- =========================================================
    WHEN LOWER(TRIM({{ date_column }})) ~ '^[0-9]+ năm trước$'
    THEN
        {{ reference_date }}
        - (
            CAST(
                REGEXP_EXTRACT(
                    LOWER(TRIM({{ date_column }})),
                    '[0-9]+'
                ) AS INTEGER
            ) * INTERVAL 1 YEAR
        )
    WHEN LOWER(TRIM({{ date_column }})) = 'một năm trước'
    THEN
        {{ reference_date }} - INTERVAL 1 YEAR

    WHEN LOWER(TRIM({{ date_column }})) = 'năm trước'
    THEN
        {{ reference_date }} - INTERVAL 1 YEAR

    -- =========================================================
    -- 6. GOOGLE MAPS EDITED TIME
    -- Ví dụ:
    -- Thời gian chỉnh sửa: 2 năm trước
    -- Thời gian chỉnh sửa: 3 năm trước
    -- Thời gian chỉnh sửa: 4 năm trước
    -- =========================================================
    WHEN LOWER(TRIM({{ date_column }}))
        ~ '^thời gian chỉnh sửa: [0-9]+ năm trước$'
    THEN
        {{ reference_date }}
        - (
            CAST(
                REGEXP_EXTRACT(
                    LOWER(TRIM({{ date_column }})),
                    '[0-9]+'
                ) AS INTEGER
            ) * INTERVAL 1 YEAR
        )
    WHEN LOWER(TRIM({{ date_column }}))
        = 'thời gian chỉnh sửa: một năm trước'
    THEN
        {{ reference_date }} - INTERVAL 1 YEAR

    -- =========================================================
    -- 7. KHÔNG NHẬN DIỆN ĐƯỢC
    -- =========================================================
    ELSE NULL

END

{% endmacro %}