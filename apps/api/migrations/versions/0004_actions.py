"""Actions the assistant proposes, and the outbox its approved emails go to."""

from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    # A proposal is decided once. Its row is the only authority on whether the action runs: the
    # decision locks it and requires 'pending', so a second approval finds it already decided.
    op.execute(
        """
        create table app.proposals (
            proposal_id bigint generated always as identity primary key,
            user_id bigint not null references app.users,
            conversation_id text not null,
            action text not null
                check (action in ('create_task', 'add_note', 'send_email')),
            account_id text not null,
            params jsonb not null,
            snapshot jsonb not null default '{}',
            status text not null default 'pending'
                check (status in ('pending', 'done', 'rejected', 'refused', 'blocked')),
            outcome jsonb not null default '{}',
            created_at timestamptz not null default now(),
            decided_at timestamptz
        )
        """
    )
    op.execute("create index proposals_by_user on app.proposals (user_id, status)")
    # shortcut: nothing delivers mail; an outbox row stands for a sent email. Add a sender that
    # reads 'queued' rows when real delivery is wired up.
    op.execute(
        """
        create table app.outbox (
            email_id bigint generated always as identity primary key,
            proposal_id bigint not null unique references app.proposals,
            account_id text not null,
            to_email text not null,
            subject text not null,
            body text not null,
            status text not null default 'sent' check (status in ('queued', 'sent')),
            created_at timestamptz not null default now()
        )
        """
    )


def downgrade() -> None:
    op.execute("drop table app.outbox")
    op.execute("drop table app.proposals")
