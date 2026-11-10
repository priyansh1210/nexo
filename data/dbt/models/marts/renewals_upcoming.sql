-- Accounts that have not renewed yet, with their health. A view because "next month" depends on today.
{{ config(materialized='view') }}

select
    accounts.account_id,
    accounts.name,
    accounts.owner_name,
    accounts.owner_email,
    accounts.plan,
    accounts.arr_usd,
    accounts.renewal_date,
    accounts.renewal_date - current_date as days_to_renewal,
    date_trunc('month', accounts.renewal_date) = date_trunc('month', current_date) + interval '1 month'
        as renews_next_month,
    health.usage_change,
    health.usage_status,
    health.usage_as_of,
    health.stale_high_tickets,
    health.overdue_invoices,
    health.risk_usage_drop,
    health.risk_stale_ticket,
    health.risk_overdue_invoice,
    health.is_at_risk
from {{ ref('dim_account') }} as accounts
join {{ ref('account_health') }} as health on health.account_id = accounts.account_id
where accounts.renewal_date >= current_date
