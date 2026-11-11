-- Application tables. Idempotent: the API runs this file at startup.
-- shortcut: no migration tool yet, which is fine while no released schema exists; adopt Alembic
-- when the first deployed schema needs changing.
create schema if not exists app;
create schema if not exists audit;

create table if not exists app.users (
    user_id bigint generated always as identity primary key,
    email text not null unique,
    name text not null,
    role text not null check (role in ('viewer', 'csm', 'admin')),
    password_hash text not null,
    created_at timestamptz not null default now()
);

-- Only a hash of the session token is stored, so a database leak does not hand out live sessions.
create table if not exists app.sessions (
    token_hash text primary key,
    user_id bigint not null references app.users on delete cascade,
    expires_at timestamptz not null
);

-- account_id points at marts.dim_account, which dbt rebuilds, so it cannot be a foreign key.
-- The API checks that the account exists before writing.
create table if not exists app.notes (
    note_id bigint generated always as identity primary key,
    account_id text not null,
    author_id bigint not null references app.users,
    body text not null,
    created_at timestamptz not null default now()
);

create table if not exists app.tasks (
    task_id bigint generated always as identity primary key,
    account_id text not null,
    title text not null,
    detail text not null default '',
    status text not null default 'open' check (status in ('open', 'done')),
    assignee_id bigint references app.users,
    created_by bigint not null references app.users,
    due_on date,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists audit.events (
    event_id bigint generated always as identity primary key,
    at timestamptz not null default now(),
    actor_id bigint references app.users,
    action text not null,
    account_id text,
    target_type text,
    target_id text,
    detail jsonb not null default '{}'
);

-- The audit log is append-only, even for the application itself.
create or replace function audit.refuse_change() returns trigger language plpgsql as $$
begin
    raise exception 'audit.events is append-only';
end
$$;

create or replace trigger events_append_only
before update or delete or truncate on audit.events
for each statement execute function audit.refuse_change();
