{#
  Rebuild Postgres views and tables in place, so the views on top of them are never dropped.

  dbt's own materializations build a new relation, swap it in and drop the old one with `cascade`.
  The cascade also drops every view built on it (`account_health` sits on the `dim_account` table)
  until later in the run recreates them. During that gap the API's account pages fail.

  Views use `create or replace view`; Postgres allows it only when the existing columns stay, in the
  same order (new ones may be added at the end). Tables build the new rows into a staging table,
  and only when its columns and types match the live table, delete and re-insert the rows in one
  transaction, so readers see the old rows until the commit. Comparing types matters: an insert
  would quietly round a value into an old, narrower column.
  Otherwise both fall back to dbt's own behaviour, which is safe because the run rebuilds the
  dependent views right after.
  shortcut: a view whose column type changed fails the run; drop that view by hand then.
  shortcut: incremental models still swap on --full-refresh (replay), dropping `fct_usage_daily` until
  it is rebuilt; give them the same treatment if replay runs while the API serves traffic.
#}
{% materialization view, adapter='postgres' %}
  {%- set existing = load_cached_relation(this) -%}
  {%- if existing is not none and existing.is_view -%}
    {%- set old_columns = adapter.get_columns_in_relation(existing) | map(attribute='name') | list -%}
    {%- set new_columns = get_columns_in_query(sql) -%}
    {%- if new_columns[:old_columns | length] == old_columns -%}
      {%- set target = this.incorporate(type='view') -%}
      {{ run_hooks(pre_hooks) }}
      {% call statement('main') -%}
        create or replace view {{ target }} as (
          {{ sql }}
        );
      {%- endcall %}
      {{ run_hooks(post_hooks) }}
      {% do adapter.commit() %}
      {{ return({'relations': [target]}) }}
    {%- endif -%}
  {%- endif -%}
  {{ return(materialization_view_default()) }}
{% endmaterialization %}

{% materialization table, adapter='postgres' %}
  {%- set existing = load_cached_relation(this) -%}
  {%- if existing is not none and existing.is_table -%}
    {%- set target = this.incorporate(type='table') -%}
    {%- set staged = make_intermediate_relation(target) -%}
    {% call statement('stage') -%}
      drop table if exists {{ staged }};
      {{ get_create_table_as_sql(False, staged, sql) }}
    {%- endcall %}
    {%- set old = adapter.get_columns_in_relation(existing) -%}
    {%- set new = adapter.get_columns_in_relation(staged) -%}
    {%- if new | map(attribute='name') | list == old | map(attribute='name') | list
        and new | map(attribute='data_type') | list == old | map(attribute='data_type') | list -%}
      {{ run_hooks(pre_hooks) }}
      {% call statement('main') -%}
        delete from {{ target }};
        insert into {{ target }} select * from {{ staged }};
        drop table {{ staged }};
      {%- endcall %}
      {{ run_hooks(post_hooks) }}
      {% do adapter.commit() %}
      {{ return({'relations': [target]}) }}
    {%- endif -%}
    {% call statement('unstage') -%}
      drop table {{ staged }};
    {%- endcall %}
  {%- endif -%}
  {{ return(materialization_table_default()) }}
{% endmaterialization %}
