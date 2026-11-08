{% test accepted_range(model, column_name, min_value=none, max_value=none, inclusive=true) %}

{#- Trả về các dòng có giá trị nằm ngoài khoảng cho phép. NULL được bỏ qua. -#}
SELECT *
FROM {{ model }}
WHERE {{ column_name }} IS NOT NULL
  AND (
        1 = 0
        {%- if min_value is not none %}
        OR {{ column_name }} {{ '<' if inclusive else '<=' }} {{ min_value }}
        {%- endif %}
        {%- if max_value is not none %}
        OR {{ column_name }} {{ '>' if inclusive else '>=' }} {{ max_value }}
        {%- endif %}
  )

{% endtest %}
