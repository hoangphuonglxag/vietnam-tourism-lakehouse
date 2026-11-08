{#-
    CHUẨN HÓA NGÀY TƯƠNG ĐỐI (relative date)
    Google Maps (và đôi khi YouTube) chỉ trả về thời gian dạng tương đối như
    "8 giờ trước", "một tháng trước", "Thời gian chỉnh sửa: 2 năm trước",
    "3 weeks ago". Ngày thực tế được ước lượng bằng:

        ngày ước lượng = ngày tham chiếu (thường là ngày crawl) - (số lượng x đơn vị)

    Bộ macro gồm:
      - relative_date_text(col)      : chuẩn hóa chuỗi (NFC, lowercase, gộp khoảng trắng,
                                       bỏ tiền tố/hậu tố "chỉnh sửa"/"edited").
      - relative_date_unit(col)      : đơn vị thời gian nhận diện được
                                       (today/second/minute/hour/day/week/month/year) hoặc NULL.
      - relative_date_quantity(col)  : số lượng (mặc định 1 cho "một", "a", "tuần trước"...).
      - normalize_relative_date(col, reference_date) : ngày ước lượng (DATE) hoặc NULL.
      - relative_date_precision(col) : độ chính xác: day / week / month / year / unknown.
-#}


{% macro relative_date_text(date_column) -%}
REGEXP_REPLACE(
    REGEXP_REPLACE(
        REGEXP_REPLACE(
            NFC_NORMALIZE(LOWER(TRIM(CAST({{ date_column }} AS VARCHAR)))),
            '\s+', ' ', 'g'
        ),
        '^(thời gian chỉnh sửa|đã chỉnh sửa|edited) ?:? ?', ''
    ),
    ' ?\((đã chỉnh sửa|edited)\)$', ''
)
{%- endmacro %}


{% macro relative_date_unit(date_column) -%}
{%- set t = relative_date_text(date_column) -%}
{%- set qty = "(([0-9]+|một|a|an|one) )?" -%}
CASE
    WHEN {{ t }} IN ('hôm nay', 'today', 'vừa xong', 'just now') THEN 'today'
    WHEN {{ t }} IN ('hôm qua', 'ngày hôm qua', 'yesterday') THEN 'day'
    WHEN REGEXP_FULL_MATCH({{ t }}, '{{ qty }}(giây|seconds?) (trước|ago)') THEN 'second'
    WHEN REGEXP_FULL_MATCH({{ t }}, '{{ qty }}(phút|minutes?) (trước|ago)') THEN 'minute'
    WHEN REGEXP_FULL_MATCH({{ t }}, '{{ qty }}(giờ|tiếng|hours?) (trước|ago)') THEN 'hour'
    WHEN REGEXP_FULL_MATCH({{ t }}, '{{ qty }}(ngày|days?) (trước|ago)') THEN 'day'
    WHEN REGEXP_FULL_MATCH({{ t }}, '{{ qty }}(tuần|weeks?) (trước|ago)') THEN 'week'
    WHEN {{ t }} = 'last week' THEN 'week'
    WHEN REGEXP_FULL_MATCH({{ t }}, '{{ qty }}(tháng|months?) (trước|ago)') THEN 'month'
    WHEN {{ t }} = 'last month' THEN 'month'
    WHEN REGEXP_FULL_MATCH({{ t }}, '{{ qty }}(năm|years?) (trước|ago)') THEN 'year'
    WHEN {{ t }} = 'last year' THEN 'year'
    ELSE NULL
END
{%- endmacro %}


{% macro relative_date_quantity(date_column) -%}
{%- set t = relative_date_text(date_column) -%}
CASE
    WHEN REGEXP_MATCHES({{ t }}, '^[0-9]+ ')
        THEN CAST(REGEXP_EXTRACT({{ t }}, '^([0-9]+)', 1) AS INTEGER)
    -- "một", "a", "an", "one", "tuần trước", "last month"... => 1
    ELSE 1
END
{%- endmacro %}


{% macro normalize_relative_date(date_column, reference_date) %}
{%- set unit = relative_date_unit(date_column) -%}
{%- set qty = relative_date_quantity(date_column) -%}
{%- set ref = "CAST(" ~ reference_date ~ " AS TIMESTAMP)" -%}
CAST(
    CASE {{ unit }}
        WHEN 'today'  THEN {{ ref }}
        WHEN 'second' THEN {{ ref }} - ({{ qty }}) * INTERVAL 1 SECOND
        WHEN 'minute' THEN {{ ref }} - ({{ qty }}) * INTERVAL 1 MINUTE
        WHEN 'hour'   THEN {{ ref }} - ({{ qty }}) * INTERVAL 1 HOUR
        WHEN 'day'    THEN {{ ref }} - ({{ qty }}) * INTERVAL 1 DAY
        WHEN 'week'   THEN {{ ref }} - ({{ qty }}) * INTERVAL 7 DAY
        WHEN 'month'  THEN {{ ref }} - ({{ qty }}) * INTERVAL 1 MONTH
        WHEN 'year'   THEN {{ ref }} - ({{ qty }}) * INTERVAL 1 YEAR
        ELSE NULL
    END
AS DATE)
{% endmacro %}


{% macro relative_date_precision(date_column) %}
CASE {{ relative_date_unit(date_column) }}
    WHEN 'today'  THEN 'day'
    WHEN 'second' THEN 'day'
    WHEN 'minute' THEN 'day'
    WHEN 'hour'   THEN 'day'
    WHEN 'day'    THEN 'day'
    WHEN 'week'   THEN 'week'
    WHEN 'month'  THEN 'month'
    WHEN 'year'   THEN 'year'
    ELSE 'unknown'
END
{% endmacro %}