select
    payload->>'account_id' as account_id,
    payload->>'name' as name,
    payload->>'domain' as domain,
    payload->>'owner_name' as owner_name,
    payload->>'owner_email' as owner_email,
    payload->>'plan' as plan,
    (payload->>'seats')::int as seats,
    (payload->>'arr_usd')::int as arr_usd,
    (payload->>'term_months')::int as term_months,
    (payload->>'contract_start')::date as contract_start,
    (payload->>'renewal_date')::date as renewal_date,
    nullif(payload->>'workspace_id', '') as workspace_id,
    nullif(payload->>'support_org_id', '') as support_org_id
from {{ latest_records('crm_accounts', 'account_id') }} as latest
