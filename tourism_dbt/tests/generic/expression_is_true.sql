{% test expression_is_true(model, expression, column_name=none) %}

{#-
    Trả về các dòng mà biểu thức điều kiện không đúng.
    Dùng được ở cấp model hoặc cấp cột (column_name được dbt truyền vào nhưng không bắt buộc dùng).
-#}
SELECT *
FROM {{ model }}
WHERE NOT ({{ expression }})

{% endtest %}
