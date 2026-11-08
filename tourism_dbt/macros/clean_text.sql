{% macro clean_text(column_name) %}
{#-
    Làm sạch văn bản tự do (review, comment, tiêu đề video).
    1. Thay thẻ <br>, <br/>, <br /> bằng khoảng trắng.
    2. Gộp nhiều khoảng trắng / xuống dòng liên tiếp thành 1 khoảng trắng.
    3. TRIM; chuỗi rỗng => NULL.
    4. Token 'nan' (do pandas ghi ra) => NULL.
-#}
{%- set cleaned -%}
NULLIF(
    TRIM(
        REGEXP_REPLACE(
            REGEXP_REPLACE(
                CAST({{ column_name }} AS VARCHAR),
                '<br\s*/?>',
                ' ',
                'gi'
            ),
            '\s+',
            ' ',
            'g'
        )
    ),
    ''
)
{%- endset -%}
CASE
    WHEN {{ cleaned }} IN ('nan', 'NaN') THEN NULL
    ELSE {{ cleaned }}
END
{% endmacro %}