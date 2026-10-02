{% macro as_of_ts() -%}
  {%- if var('as_of') == 'now' -%} current_timestamp
  {%- else -%} cast('{{ var("as_of") }}' as timestamp)
  {%- endif -%}
{%- endmacro %}

{# Use the bare schema name (bronze/silver/gold) instead of dbt's default target_schema prefix. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
  {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}
