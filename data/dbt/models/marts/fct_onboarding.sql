-- When each account reached each onboarding step. A missing date means the step was never reached.
select
    map.account_id,
    min(staged.occurred_at) filter (where staged.step = 'kickoff') as kickoff_at,
    min(staged.occurred_at) filter (where staged.step = 'admin_setup') as admin_setup_at,
    min(staged.occurred_at) filter (where staged.step = 'team_invited') as team_invited_at,
    min(staged.occurred_at) filter (where staged.step = 'data_import') as data_import_at,
    min(staged.occurred_at) filter (where staged.step = 'go_live') as go_live_at,
    count(distinct staged.step)::int as steps_completed,
    bool_or(staged.step = 'go_live') as is_complete
from {{ ref('identity_map') }} as map
join {{ ref('stg_events') }} as staged on staged.workspace_id = map.workspace_id
where staged.event_name = 'onboarding_step'
group by map.account_id
