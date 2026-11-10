-- The review queue: records that could not be tied to an account. They are kept, never dropped,
-- and an account listed here must be reported as "no linked workspace", not as zero usage.
select
    'workspace_without_account' as problem,
    events.workspace_id as key,
    count(*) as records,
    max(events.occurred_at) as last_seen
from {{ ref('stg_events') }} as events
left join {{ ref('identity_map') }} as map on map.workspace_id = events.workspace_id
where map.account_id is null
group by events.workspace_id

union all

select
    'org_without_account' as problem,
    tickets.org_id as key,
    count(*) as records,
    max(tickets.created_at) as last_seen
from {{ ref('stg_tickets') }} as tickets
left join {{ ref('identity_map') }} as map on map.support_org_id = tickets.org_id
where map.account_id is null
group by tickets.org_id

union all

select
    'account_without_workspace' as problem,
    account_id as key,
    0 as records,
    null::timestamptz as last_seen
from {{ ref('identity_map') }}
where workspace_id is null
