-- Usage in the last 30 days against the 30 days before. Both windows end on the latest day that
-- has data (as_of_day), not on today, so a stopped pipeline never shows up as a fake usage drop.
with bounds as (
    select max(day) as as_of_day from {{ ref('int_usage_daily') }}
),

events as (
    select
        map.account_id,
        coalesce(sum(daily.events) filter (where daily.day > bounds.as_of_day - 30), 0) as events_last_30d,
        coalesce(sum(daily.events) filter (where daily.day <= bounds.as_of_day - 30), 0) as events_prior_30d
    from {{ ref('identity_map') }} as map
    join {{ ref('int_usage_daily') }} as daily on daily.workspace_id = map.workspace_id
    cross join bounds
    where daily.day > bounds.as_of_day - 60
    group by map.account_id
),

users as (
    select
        map.account_id,
        count(distinct staged.user_id) filter (where staged.day > bounds.as_of_day - 30) as active_users_last_30d,
        count(distinct staged.user_id) filter (where staged.day <= bounds.as_of_day - 30) as active_users_prior_30d
    from {{ ref('identity_map') }} as map
    join {{ ref('stg_events') }} as staged on staged.workspace_id = map.workspace_id
    cross join bounds
    where staged.day > bounds.as_of_day - 60 and staged.event_name in ('login', 'feature_used')
    group by map.account_id
)

select
    events.account_id,
    bounds.as_of_day,
    events.events_last_30d::int as events_last_30d,
    events.events_prior_30d::int as events_prior_30d,
    case
        when events.events_prior_30d > 0
            then round(events.events_last_30d / events.events_prior_30d - 1, 4)
    end as usage_change,
    users.active_users_last_30d::int as active_users_last_30d,
    users.active_users_prior_30d::int as active_users_prior_30d
from events
join users on users.account_id = events.account_id
cross join bounds
