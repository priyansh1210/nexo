import os
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import psycopg
from fastapi import Depends
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


def connect() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def get_db() -> Iterator[psycopg.Connection]:
    # One transaction per request: it commits when the route returns and rolls back when it raises,
    # so a write and its audit row always land together.
    # shortcut: a new connection per request, fine for a team-sized deployment; switch to
    # psycopg_pool when request volume makes connection setup show up.
    with connect() as conn:
        yield conn


# scope="function" commits before the response is sent. With the default, the reply goes out first,
# so a client acting on it at once would not find its own write, and a failed commit would already
# have been reported as a success.
Db = Annotated[psycopg.Connection, Depends(get_db, scope="function")]


def audit(
    db: psycopg.Connection,
    actor: dict,
    action: str,
    *,
    account_id: str | None = None,
    target: tuple[str, object] | None = None,
    detail: dict | None = None,
) -> None:
    """Record who did what. Call it in the same transaction as the write it describes."""
    target_type, target_id = (target[0], str(target[1])) if target else (None, None)
    db.execute(
        "insert into audit.events (actor_id, action, account_id, target_type, target_id, detail) "
        "values (%s, %s, %s, %s, %s, %s)",
        (actor["user_id"], action, account_id, target_type, target_id, Jsonb(detail or {})),
    )
