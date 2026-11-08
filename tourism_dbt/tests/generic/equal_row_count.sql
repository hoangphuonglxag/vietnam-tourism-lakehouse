{% test equal_row_count(model, compare_model, compare_filter=none, compare_distinct_column=none) %}

{#-
    Kiểm tra số dòng trước và sau xử lý / join.
    - model                  : model sau xử lý (bảng Silver).
    - compare_model          : model trước xử lý (thường là staging hoặc bảng dimension).
    - compare_filter         : điều kiện lọc áp dụng lên compare_model (vd: chỉ bản ghi hợp lệ).
    - compare_distinct_column: nếu có, đếm DISTINCT biểu thức này thay vì COUNT(*)
                               (dùng khi model đã khử trùng lặp theo khóa).
    Test thất bại (trả về 1 dòng) nếu hai con số khác nhau.
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
)

SELECT
    model_rows,
    compare_rows,
    model_rows - compare_rows AS row_difference
FROM model_count
CROSS JOIN compare_count
WHERE model_rows <> compare_rows

{% endtest %}
