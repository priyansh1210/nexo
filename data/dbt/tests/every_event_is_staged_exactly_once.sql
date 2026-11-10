-- Fails if deduplication lost an event or kept a duplicate.
with landed as (
    select count(distinct {{ event_id() }}) as events from {{ source('raw', 'product_events') }}
),

staged as (
    select count(*) as events from {{ ref('stg_events') }}
)

select landed.events as landed, staged.events as staged
from landed
cross join staged
where landed.events <> staged.events
