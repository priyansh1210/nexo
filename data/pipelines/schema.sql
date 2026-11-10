-- Pipeline bookkeeping. Idempotent: the runner executes this file before every sync.
create schema if not exists raw;
create schema if not exists meta;

create table if not exists meta.sources (
    source text primary key,
    expected_every interval not null,
    -- Set by `stall`: the source is skipped and reads as if it last synced at this time.
    stalled_since timestamptz
);

create table if not exists meta.cursors (
    source text not null,
    stream text not null,
    cursor text not null,
    primary key (source, stream)
);

create table if not exists meta.sync_runs (
    id bigint generated always as identity primary key,
    source text not null,
    batch_id uuid not null,
    status text not null check (status in ('success', 'failed')),
    records int not null default 0,
    error text,
    started_at timestamptz not null,
    finished_at timestamptz not null default clock_timestamp()
);

-- Results of the latest warehouse build's tests, one row per test.
create table if not exists meta.check_results (
    model text not null,
    test text not null,
    status text not null,
    failures int,
    checked_at timestamptz not null default now()
);

-- A view, not a table: a stopped pipeline cannot update a status, but a view is always current.
-- A source is stale once its last successful sync is older than twice its expected interval.
create or replace view meta.source_freshness as
with last_sync as (
    select
        s.source,
        s.expected_every,
        s.stalled_since is not null as is_stalled,
        least(max(r.finished_at) filter (where r.status = 'success'), s.stalled_since) as last_updated
    from meta.sources s
    left join meta.sync_runs r using (source)
    group by s.source, s.expected_every, s.stalled_since
)
select
    source,
    last_updated,
    expected_every,
    is_stalled,
    case
        when last_updated is null or last_updated < now() - expected_every * 2 then 'stale'
        else 'fresh'
    end as status
from last_sync;
