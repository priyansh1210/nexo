select
    payload->>'invoice_id' as invoice_id,
    payload->>'account_id' as account_id,
    (payload->>'amount_usd')::int as amount_usd,
    (payload->>'issued_on')::date as issued_on,
    (payload->>'due_on')::date as due_on,
    payload->>'status' as status,
    nullif(payload->>'paid_on', '')::date as paid_on
from {{ latest_records('billing_invoices', 'invoice_id') }} as latest
