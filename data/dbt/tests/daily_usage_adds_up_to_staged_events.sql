-- Fails if the incremental daily table drifted from the events it is built on: a day counted twice
-- after a late arrival, a day missed, or more than one row for a workspace, day and feature.
with daily as (
    select
        coalesce(sum(events), 0) as events,
        count(*) as row_count,
        count(distinct (workspace_id, day, feature)) as distinct_grains
    from {{ ref('int_usage_daily') }}
),

staged as (
    select count(*) as events
    from {{ ref('stg_events') }}
    where event_name in ('login', 'feature_used')
)

select daily.events as daily_events, staged.events as staged_events, daily.row_count, daily.distinct_grains
from daily
cross join staged
where daily.events <> staged.events or daily.row_count <> daily.distinct_grains
