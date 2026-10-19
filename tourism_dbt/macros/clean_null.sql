{% macro clean_null(column_name) %}

NULLIF(
    TRIM({{ column_name }}),
    ''
)

{% endmacro %}