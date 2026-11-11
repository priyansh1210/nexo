"""${message}"""

from alembic import op

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}


def upgrade() -> None:
    op.execute("")


def downgrade() -> None:
    op.execute("")
