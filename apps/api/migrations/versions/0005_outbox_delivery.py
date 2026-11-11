"""Approved emails are now delivered: queued until the sender takes them (apps/api/outbox.py).

This replaces the stand-in noted in 0004, where an outbox row counted as a sent email.
"""

from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute("alter table app.outbox drop constraint outbox_status_check")
    # Rows written before this were never delivered; say so instead of 'sent'.
    op.execute("update app.outbox set status = 'logged' where status = 'sent'")
    op.execute(
        """
        alter table app.outbox
            alter column status set default 'queued',
            add constraint outbox_status_check
                check (status in ('queued', 'sent', 'logged', 'failed')),
            add column attempts int not null default 0,
            add column last_error text,
            add column sent_at timestamptz
        """
    )


def downgrade() -> None:
    op.execute("alter table app.outbox drop constraint outbox_status_check")
    op.execute("update app.outbox set status = 'sent' where status <> 'sent'")
    op.execute(
        """
        alter table app.outbox
            alter column status set default 'sent',
            add constraint outbox_status_check check (status in ('queued', 'sent')),
            drop column attempts,
            drop column last_error,
            drop column sent_at
        """
    )
