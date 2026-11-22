{% macro clean_null(column_name) %}
{#-
    Chuẩn hóa giá trị rỗng về NULL.
    - Ép về VARCHAR (Bronze có thể suy luận kiểu khác nhau giữa các file JSONL).
    - TRIM khoảng trắng và ký tự nháy kép/đơn bao bọc.
    - '' và các token rỗng do pandas/Python sinh ra ('nan', 'none', 'null', 'nat', '""') => NULL.
-#}
{%- set raw_str = "TRIM(TRIM(CAST(" ~ column_name ~ " AS VARCHAR)), '\"')" -%}
CASE
    WHEN {{ raw_str }} IS NULL OR LOWER(TRIM({{ raw_str }})) IN ('', 'nan', 'none', 'null', 'nat')
        THEN NULL
    ELSE TRIM({{ raw_str }})
END
{% endmacro %}
