-- The risk criteria, each with the inputs it was decided on. A view because ticket age and overdue
-- invoices depend on today. Thresholds are the vars in dbt_project.yml.
{{ config(materialized='view') }}

with tickets as (
    select account_id, count(*) as stale_high_tickets
    from {{ ref('fct_tickets') }}
    where is_open and severity in ('high', 'urgent') and age_days > {{ var('risk_ticket_age_days') }}
    group by account_id
),

invoices as (
    select account_id, count(*) as overdue_invoices
    from {{ ref('stg_invoices') }}
    where status = 'overdue' or (paid_on is null and due_on < current_date)
    group by account_id
),

signals as (
    select
        accounts.account_id,
        trend.usage_change,
        trend.as_of_day as usage_as_of,
        -- Anything but 'ok' means usage_change is unknown, which is not the same as no decline.
        case
            when accounts.workspace_id is null then 'no_linked_workspace'
            when trend.account_id is null then 'no_recent_usage'
            when trend.events_prior_30d = 0 then 'no_baseline'
            else 'ok'
        end as usage_status,
        coalesce(tickets.stale_high_tickets, 0)::int as stale_high_tickets,
        coalesce(invoices.overdue_invoices, 0)::int as overdue_invoices
    from {{ ref('dim_account') }} as accounts
    left join {{ ref('fct_usage_trend') }} as trend on trend.account_id = accounts.account_id
    left join tickets on tickets.account_id = accounts.account_id
    left join invoices on invoices.account_id = accounts.account_id
),

risks as (
    select
        *,
        coalesce(usage_change <= {{ var('risk_usage_drop') }}, false) as risk_usage_drop,
        stale_high_tickets > 0 as risk_stale_ticket,
        overdue_invoices > 0 as risk_overdue_invoice
    from signals
)

select *, risk_usage_drop or risk_stale_ticket or risk_overdue_invoice as is_at_risk
from risks
