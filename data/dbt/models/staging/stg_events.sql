-- Deduplicated product events. Incremental: each run adds only event ids it has not staged before,
-- so a duplicate delivery changes nothing, whenever it arrives. The first arrival wins.
{{ config(
    materialized='incremental',
    incremental_strategy='append',
    indexes=[{'columns': ['event_id'], 'unique': true}, {'columns': ['_staged_at']}]
) }}

with first_arrival as (
    select distinct on ({{ event_id() }})
        {{ event_id() }} as event_id,
        payload->>'workspace_id' as workspace_id,
        payload->>'user_id' as user_id,
        payload->>'name' as event_name,
        payload->'properties'->>'feature' as feature,
        payload->'properties'->>'step' as step,
        (payload->>'occurred_at')::timestamptz as occurred_at
    from {{ source('raw', 'product_events') }}
    order by {{ event_id() }}, _ingested_at
)

select
    *,
    (occurred_at at time zone 'utc')::date as day,
    -- When this row was staged. Downstream models use it to find the days that received new events.
    '{{ run_started_at }}'::timestamptz as _staged_at
from first_arrival
{% if is_incremental() %}
where not exists (select 1 from {{ this }} as staged where staged.event_id = first_arrival.event_id)
{% endif %}
