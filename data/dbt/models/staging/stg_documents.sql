select
    payload->>'doc_id' as doc_id,
    payload->>'account_id' as account_id,
    payload->>'kind' as kind,
    payload->>'title' as title,
    payload->>'body' as body,
    payload->>'author' as author,
    (payload->>'created_at')::timestamptz as created_at
from {{ latest_records('documents', 'doc_id') }} as latest
