select
    payload->>'ticket_id' as ticket_id,
    payload->>'org_id' as org_id,
    payload->>'requester_email' as requester_email,
    payload->>'subject' as subject,
    payload->>'body' as body,
    payload->>'severity' as severity,
    payload->>'status' as status,
    (payload->>'created_at')::timestamptz as created_at,
    (payload->>'updated_at')::timestamptz as updated_at,
    (payload->>'solved_at')::timestamptz as solved_at
from {{ latest_records('support_tickets', 'ticket_id') }} as latest
