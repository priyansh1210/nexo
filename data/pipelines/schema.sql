-- Pipeline bookkeeping. Idempotent: the runner executes this file before every sync.
create schema if not exists raw;
create schema if not exists meta;
create schema if not exists vec;
create extension if not exists vector;

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

-- A record a connector could not read: kept here instead of stopping its source.
create table if not exists meta.dead_letters (
    id bigint generated always as identity primary key,
    source text not null,
    stream text not null,
    batch_id uuid not null,
    record text not null,
    error text not null,
    at timestamptz not null default now()
);
alter table meta.sync_runs add column if not exists rejected int not null default 0;

-- Results of the latest warehouse build's tests, one row per test.
create table if not exists meta.check_results (
    model text not null,
    test text not null,
    status text not null,
    failures int,
    checked_at timestamptz not null default now()
);

-- One row per warehouse build. A source's data reaches the marts only when a build runs after it.
create table if not exists meta.build_runs (
    finished_at timestamptz not null default now(),
    success boolean not null
);

-- Document passages and their embeddings, for search. Rebuilt after every warehouse build.
create table if not exists vec.document_chunks (
    doc_id text primary key,
    account_id text not null,
    kind text not null,
    title text not null,
    author text not null,
    created_at timestamptz not null,
    body text not null,
    embedding vector(256) not null
);

-- A view, not a table: a stopped pipeline cannot update a status, but a view is always current.
-- A source is as fresh as the older of its last successful delivery and the last warehouse build,
-- because the marts hold its data only as of that build. It is stale once that is older than twice
-- its expected interval.
create or replace view meta.source_freshness as
with last_build as (
    select max(finished_at) as finished_at from meta.build_runs
),

last_sync as (
    select
        s.source,
        s.expected_every,
        s.stalled_since is not null as is_stalled,
        -- least() skips nulls, so a source never delivered or never built is null (stale) here.
        case
            when (select finished_at from last_build) is not null
                and max(r.finished_at) filter (where r.status = 'success') is not null
                then least(
                    max(r.finished_at) filter (where r.status = 'success'),
                    s.stalled_since,
                    (select finished_at from last_build)
                )
        end as last_updated
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
    end as status,
    -- Records that could not be read lately: the source still flows, but its totals may be low.
    (
        select count(*) from meta.dead_letters d
        where d.source = last_sync.source and d.at > now() - interval '1 day'
    )::int as rejected_last_day
from last_sync;
