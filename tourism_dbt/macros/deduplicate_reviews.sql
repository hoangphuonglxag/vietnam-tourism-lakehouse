{% macro deduplicate_by_key(relation, key_column) %}

SELECT *
FROM (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY {{ key_column }}
            ORDER BY crawled_at_utc DESC
        ) AS rn
    FROM {{ relation }}
)
WHERE rn = 1

{% endmacro %}