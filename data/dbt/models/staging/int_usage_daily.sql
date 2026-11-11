-- Usage per workspace, day and feature. Incremental by day: a run recomputes exactly the days that
-- received newly staged events, however late those events arrived, and leaves every other day alone.
-- A replay can also force a range of days with the replay_from and replay_to variables.
-- Logins have no feature, so they count under 'login'; a feature event that names no feature counts
-- under 'feature_used' rather than inflating logins.
{{ config(materialized='incremental', incremental_strategy='delete+insert', unique_key='day') }}

select
    workspace_id,
    day,
    coalesce(feature, event_name) as feature,
    count(*) as events,
    count(distinct user_id) as users,
    max(_staged_at) as _staged_at
from {{ ref('stg_events') }}
where event_name in ('login', 'feature_used')
{% if is_incremental() %}
    and day in (
        select distinct day
        from {{ ref('stg_events') }}
        where _staged_at > (select coalesce(max(_staged_at), '-infinity') from {{ this }})
        {% if var('replay_from', none) %}
        union
        select generate_series('{{ var("replay_from") }}'::date, '{{ var("replay_to") }}'::date, '1 day')::date
        {% endif %}
    )
{% endif %}
group by workspace_id, day, coalesce(feature, event_name)
