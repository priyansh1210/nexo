-- A view because a ticket's age depends on today.
{{ config(materialized='view') }}

select
    tickets.ticket_id,
    map.account_id,
    tickets.org_id,
    tickets.requester_email,
    tickets.subject,
    tickets.body,
    tickets.severity,
    tickets.status,
    tickets.created_at,
    tickets.updated_at,
    tickets.solved_at,
    tickets.status <> 'solved' as is_open,
    current_date - (tickets.created_at at time zone 'utc')::date as age_days
from {{ ref('stg_tickets') }} as tickets
left join {{ ref('identity_map') }} as map on map.support_org_id = tickets.org_id
