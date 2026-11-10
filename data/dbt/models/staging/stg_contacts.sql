select
    payload->>'contact_id' as contact_id,
    payload->>'account_id' as account_id,
    payload->>'name' as name,
    payload->>'email' as email,
    payload->>'role' as role,
    (payload->>'is_active')::boolean as is_active
from {{ latest_records('crm_contacts', 'contact_id') }} as latest
