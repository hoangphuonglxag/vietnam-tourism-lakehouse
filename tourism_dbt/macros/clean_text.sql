{% macro clean_text(column_name) %}

NULLIF(
    TRIM(
        REGEXP_REPLACE(
            {{ column_name }},
            '<br\s*/?>',
            ' ',
            'g'
        )
    ),
    ''
)

{% endmacro %}