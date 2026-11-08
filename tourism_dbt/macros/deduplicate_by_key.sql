{% macro deduplicate_by_key(relation, partition_by, order_by='crawled_at_utc DESC') %}
{#-
    Giữ lại đúng 1 bản ghi cho mỗi khóa nghiệp vụ.
    - relation    : ref(), source() hoặc tên CTE.
    - partition_by: tên cột (string) hoặc danh sách cột tạo thành khóa.
    - order_by    : thứ tự ưu tiên, bản ghi đứng đầu được giữ (mặc định: lần crawl mới nhất).
    Dùng QUALIFY của DuckDB nên không sinh thêm cột phụ (rn) vào kết quả.
-#}
{%- if partition_by is string -%}
    {%- set partition_clause = partition_by -%}
{%- else -%}
    {%- set partition_clause = partition_by | join(', ') -%}
{%- endif -%}
SELECT *
FROM {{ relation }}
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY {{ partition_clause }}
    ORDER BY {{ order_by }}
) = 1
{% endmacro %}