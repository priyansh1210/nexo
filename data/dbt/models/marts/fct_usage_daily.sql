-- Daily usage by account and feature. A view over the incremental table, so a workspace linked to
-- its account later gets its whole history without a backfill.
{{ config(materialized='view') }}

select map.account_id, daily.workspace_id, daily.day, daily.feature, daily.events, daily.users
from {{ ref('int_usage_daily') }} as daily
join {{ ref('identity_map') }} as map on map.workspace_id = daily.workspace_id
