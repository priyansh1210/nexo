"""API keys: how a machine, such as a product backend, signs in to push data."""

from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    # Like sessions, only the hash of a key is stored. A revoked key keeps its row for the record.
    op.execute(
        """
        create table app.api_keys (
            key_id bigint generated always as identity primary key,
            name text not null,
            key_hash text not null unique,
            created_by bigint not null references app.users,
            created_at timestamptz not null default now(),
            revoked_at timestamptz
        )
        """
    )


def downgrade() -> None:
    op.execute("drop table app.api_keys")
