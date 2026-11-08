{% test unique_combination_of_columns(model, combination_of_columns) %}

{#- Trả về các tổ hợp khóa xuất hiện nhiều hơn 1 lần (vi phạm grain của bảng). -#}
SELECT
    {{ combination_of_columns | join(', ') }},
    COUNT(*) AS duplicate_count
FROM {{ model }}
GROUP BY {{ combination_of_columns | join(', ') }}
HAVING COUNT(*) > 1

{% endtest %}
