-- Fails if the per-feature events do not add up to the account's totals in fct_usage_trend.
select trend.account_id
from {{ ref('fct_usage_trend') }} as trend
join (
    select account_id, sum(events_last_30d) as last_30d, sum(events_prior_30d) as prior_30d
    from {{ ref('fct_usage_by_feature') }}
    group by account_id
) as features on features.account_id = trend.account_id
where features.last_30d <> trend.events_last_30d or features.prior_30d <> trend.events_prior_30d
