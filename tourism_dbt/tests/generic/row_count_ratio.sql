{% test row_count_ratio(model, compare_model, min_ratio=0.95, max_ratio=1.0, compare_filter=none, compare_distinct_column=none) %}

{#-
    Kiểm tra coverage: ratio = số dòng model / số dòng (hoặc số khóa distinct) của compare_model.
    Test thất bại nếu ratio nằm ngoài [min_ratio, max_ratio].
    Nếu compare_model không có dòng nào thì ratio = 0 (coi là thiếu dữ liệu).
-#}
WITH model_count AS (
    SELECT COUNT(*) AS model_rows
    FROM {{ model }}
),

compare_count AS (
    SELECT
        {% if compare_distinct_column -%}
        COUNT(DISTINCT {{ compare_distinct_column }})
        {%- else -%}
        COUNT(*)
        {%- endif %} AS compare_rows
    FROM {{ compare_model }}
    {% if compare_filter -%}
    WHERE {{ compare_filter }}
    {%- endif %}
),

coverage AS (
    SELECT
        model_rows,
        compare_rows,
        CASE
            WHEN compare_rows = 0 THEN 0
            ELSE model_rows * 1.0 / compare_rows
        END AS coverage_ratio
    FROM model_count
    CROSS JOIN compare_count
)

SELECT *
FROM coverage
WHERE coverage_ratio < {{ min_ratio }}
   OR coverage_ratio > {{ max_ratio }}

{% endtest %}
