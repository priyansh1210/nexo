-- Usage per account and feature: the last 30 days against the 30 before, on the same windows as
-- fct_usage_trend (ending on the latest day that has data). Features are named as in int_usage_daily.
with bounds as (
    select max(day) as as_of_day from {{ ref('int_usage_daily') }}
),

events as (
    select
        map.account_id,
        daily.feature,
        coalesce(sum(daily.events) filter (where daily.day > bounds.as_of_day - 30), 0) as events_last_30d,
        coalesce(sum(daily.events) filter (where daily.day <= bounds.as_of_day - 30), 0) as events_prior_30d
    from {{ ref('identity_map') }} as map
    join {{ ref('int_usage_daily') }} as daily on daily.workspace_id = map.workspace_id
    cross join bounds
    where daily.day > bounds.as_of_day - 60
    group by map.account_id, daily.feature
),

-- Distinct users are counted from the events themselves: daily distinct counts cannot be added up.
users as (
    select
        map.account_id,
        coalesce(staged.feature, staged.event_name) as feature,
        count(distinct staged.user_id) filter (where staged.day > bounds.as_of_day - 30) as users_last_30d,
        count(distinct staged.user_id) filter (where staged.day <= bounds.as_of_day - 30) as users_prior_30d
    from {{ ref('identity_map') }} as map
    join {{ ref('stg_events') }} as staged on staged.workspace_id = map.workspace_id
    cross join bounds
    where staged.day > bounds.as_of_day - 60 and staged.event_name in ('login', 'feature_used')
    group by map.account_id, coalesce(staged.feature, staged.event_name)
)

select
    events.account_id,
    events.feature,
    bounds.as_of_day,
    events.events_last_30d::int as events_last_30d,
    events.events_prior_30d::int as events_prior_30d,
    case
        when events.events_prior_30d > 0
            then round(events.events_last_30d / events.events_prior_30d - 1, 4)
    end as usage_change,
    users.users_last_30d::int as users_last_30d,
    users.users_prior_30d::int as users_prior_30d
from events
join users on users.account_id = events.account_id and users.feature = events.feature
cross join bounds
