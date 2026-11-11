"""Delivers approved emails from app.outbox. Runs as its own process: python -m apps.api.outbox

With NEXO_SMTP_HOST set, each queued email is sent over SMTP. Without it nothing is delivered: the
email is written to the log and marked 'logged', so the demo needs no mail server and never claims
that an email went out.

Delivery is at least once: an email is marked sent after the server accepted it, so a crash between
the two sends it again on the next run.
"""

import logging
import os
import smtplib
import time
from collections import Counter
from email.message import EmailMessage

import psycopg
from psycopg.rows import dict_row

from apps.api.db import audit

MAX_ATTEMPTS = 5  # then the email is marked failed and left for a person to look at
EVERY_SECONDS = 30  # how long an approved email waits at most
log = logging.getLogger(__name__)


def deliver_smtp(message: EmailMessage) -> None:
    port = int(os.environ.get("NEXO_SMTP_PORT") or 587)
    with smtplib.SMTP(os.environ["NEXO_SMTP_HOST"], port, timeout=30) as smtp:
        if os.environ.get("NEXO_SMTP_STARTTLS", "1") == "1":
            smtp.starttls()
        if user := os.environ.get("NEXO_SMTP_USER"):
            smtp.login(user, os.environ.get("NEXO_SMTP_PASSWORD", ""))
        smtp.send_message(message)


def message(row: dict) -> EmailMessage:
    email = EmailMessage()
    email["From"] = os.environ.get("NEXO_SMTP_FROM") or "nexo@localhost"
    email["To"] = row["to_email"]
    email["Reply-To"] = row["approved_by"]  # replies go to the CSM who approved it
    email["Subject"] = row["subject"]
    email.set_content(row["body"])
    return email


def send_queued(conn: psycopg.Connection, deliver=None) -> Counter:
    """Try every queued email once. Returns how many were sent, logged, retried and failed.

    `conn` must be in autocommit mode: each email is locked, sent and marked in its own transaction,
    so two senders never take the same email.
    """
    if deliver is None and os.environ.get("NEXO_SMTP_HOST"):
        deliver = deliver_smtp
    outcomes, after = Counter(), 0
    while True:
        with conn.transaction():
            row = conn.execute(
                "select o.*, u.email as approved_by from app.outbox o "
                "join app.proposals p using (proposal_id) join app.users u on u.user_id = p.user_id "
                "where o.status = 'queued' and o.email_id > %s "
                "order by o.email_id limit 1 for update of o skip locked",
                (after,),
            ).fetchone()
            if not row:
                return outcomes
            after, error = row["email_id"], None
            if deliver is None:
                log.info("No SMTP server set; not delivered:\n%s", message(row))
                status = "logged"
            else:
                try:
                    deliver(message(row))
                    status = "sent"
                except (smtplib.SMTPException, OSError) as failure:
                    error = f"{type(failure).__name__}: {failure}"[:500]
                    status = "failed" if row["attempts"] + 1 >= MAX_ATTEMPTS else "queued"
            conn.execute(
                "update app.outbox set status = %s, attempts = attempts + 1, last_error = %s, "
                "sent_at = case when %s = 'sent' then now() end where email_id = %s",
                (status, error, status, row["email_id"]),
            )
            outcome = "retry" if status == "queued" else status
            detail = {"to": row["to_email"], "attempt": row["attempts"] + 1, "error": error}
            audit(
                conn,
                {"user_id": None},  # the sender is the system, acting on an approval
                f"email.{outcome}",
                account_id=row["account_id"],
                target=("email", row["email_id"]),
                detail=detail,
            )
            outcomes[outcome] += 1


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    while True:
        try:
            with psycopg.connect(
                os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row
            ) as conn:
                if outcomes := send_queued(conn):
                    log.info("emails: %s", dict(outcomes))
        except psycopg.Error as error:  # the database is restarting: try again next round
            log.warning("could not reach the outbox: %s", error)
        time.sleep(EVERY_SECONDS)


if __name__ == "__main__":
    main()
