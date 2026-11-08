{% macro clean_null(column_name) %}
{#-
    Chuẩn hóa giá trị rỗng về NULL.
    - Ép về VARCHAR (Bronze có thể suy luận kiểu khác nhau giữa các file JSONL).
    - TRIM khoảng trắng.
    - '' và các token rỗng do pandas/Python sinh ra ('nan', 'none', 'null', 'nat') => NULL.
-#}
CASE
    WHEN LOWER(TRIM(CAST({{ column_name }} AS VARCHAR))) IN ('', 'nan', 'none', 'null', 'nat')
        THEN NULL
    ELSE TRIM(CAST({{ column_name }} AS VARCHAR))
END
{% endmacro %}