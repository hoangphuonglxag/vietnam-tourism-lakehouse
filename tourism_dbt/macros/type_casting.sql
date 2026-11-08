{#-
    Các macro ép kiểu an toàn cho dữ liệu Bronze.
    Bronze giữ nguyên giá trị nguồn (hầu hết là chuỗi, ví dụ "5", "0", "False", ""),
    vì vậy mọi phép ép kiểu đều dùng TRY_CAST: giá trị sai định dạng => NULL thay vì lỗi.
-#}

{% macro to_int(column_name) %}
TRY_CAST(TRY_CAST({{ clean_null(column_name) }} AS DOUBLE) AS BIGINT)
{% endmacro %}


{% macro to_double(column_name) %}
TRY_CAST({{ clean_null(column_name) }} AS DOUBLE)
{% endmacro %}


{% macro to_bool(column_name) %}
CASE
    WHEN LOWER({{ clean_null(column_name) }}) IN ('true', 't', '1', 'yes', 'y') THEN TRUE
    WHEN LOWER({{ clean_null(column_name) }}) IN ('false', 'f', '0', 'no', 'n') THEN FALSE
    ELSE NULL
END
{% endmacro %}


{% macro to_utc_timestamp(column_name) %}
{#-
    Chuẩn hóa timestamp về UTC, kiểu TIMESTAMP (không kèm timezone).
    - Có offset (Z, +00:00, -07:00...) => quy đổi về UTC.
    - Không có offset (một số dữ liệu historical) => coi như đã là UTC.
    - Không parse được => NULL.
-#}
{%- set v = clean_null(column_name) -%}
CASE
    WHEN {{ v }} IS NULL THEN NULL
    WHEN REGEXP_MATCHES({{ v }}, '[0-9]{2}:[0-9]{2}.*([Zz]|[+-][0-9]{2}(:?[0-9]{2})?)$')
        THEN TRY_CAST({{ v }} AS TIMESTAMPTZ) AT TIME ZONE 'UTC'
    ELSE TRY_CAST({{ v }} AS TIMESTAMP)
END
{% endmacro %}


{% macro normalize_province_id(column_name) %}
{#-
    Chuẩn hóa province_id về dạng chuỗi 2 ký tự.
    Data contract: province_id xuất hiện là '01' ở file OSM/province nhưng là '1'
    (hoặc '1.0' do pandas) ở các CSV downstream => chuẩn hóa thành '01'.
-#}
{%- set v = clean_null(column_name) -%}
CASE
    WHEN {{ v }} IS NULL THEN NULL
    WHEN REGEXP_FULL_MATCH({{ v }}, '[0-9]+(\.0+)?')
        THEN LPAD(CAST(CAST(TRY_CAST({{ v }} AS DOUBLE) AS BIGINT) AS VARCHAR), 2, '0')
    ELSE UPPER({{ v }})
END
{% endmacro %}
