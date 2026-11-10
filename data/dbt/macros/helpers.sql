{# Use the configured schema name as it is, instead of dbt's default "<target>_<custom>". #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name | trim if custom_schema_name else target.schema }}
{%- endmacro %}

{# The newest landed version of each record. raw is append-only, so older versions stay there. #}
{# shortcut: a record deleted at the source keeps its last version here; add tombstones when a real CRM is connected. #}
{% macro latest_records(table, key) -%}
    (
        select distinct on (payload->>'{{ key }}') payload
        from {{ source('raw', table) }}
        order by payload->>'{{ key }}', _ingested_at desc
    )
{%- endmacro %}

{# An event's identity: its own id, or a hash of what happened when the source sent none. #}
{% macro event_id() -%}
    coalesce(
        nullif(payload->>'event_id', ''),
        md5(concat_ws('|', payload->>'workspace_id', payload->>'user_id', payload->>'name', payload->>'occurred_at'))
    )
{%- endmacro %}
