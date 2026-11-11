"""Failed sign-in attempts, for rate limiting."""

from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.execute(
        """
        create table app.login_attempts (
            email text not null,
            at timestamptz not null default now()
        )
        """
    )
    op.execute("create index login_attempts_by_email on app.login_attempts (email, at)")


def downgrade() -> None:
    op.execute("drop table app.login_attempts")
