"""Real users: an admin adds them through the API; the first admin is created from the command line.

python -m apps.api.users create --email you@company.com --name "Your Name" --role admin

In the Compose stack: docker compose exec api python -m apps.api.users create ...
The password is asked for, never passed as an argument, so it stays out of shell history.
"""

import argparse
import getpass
import sys
from datetime import datetime
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from apps.api.auth import Admin, hash_password
from apps.api.db import Db, audit, connect, migrate

router = APIRouter(tags=["users"])

MIN_PASSWORD = 12
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    ),
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Role = Literal["viewer", "csm", "admin"]


class UserIn(BaseModel):
    email: Email
    name: Name
    role: Role
    password: str = Field(min_length=MIN_PASSWORD, max_length=200)


class UserOut(BaseModel):
    user_id: int
    email: str
    name: str
    role: str
    created_at: datetime


def create_user(db: psycopg.Connection, new: UserIn) -> dict:
    """Insert a user. Raises ValueError when the email is already taken."""
    created = db.execute(
        "insert into app.users (email, name, role, password_hash) values (%s, %s, %s, %s) "
        "on conflict (email) do nothing returning user_id, email, name, role, created_at",
        (new.email, new.name, new.role, hash_password(new.password)),
    ).fetchone()
    if not created:
        raise ValueError(f"A user with the email {new.email} already exists")
    return created


@router.post("/users", status_code=201)
def add_user(new: UserIn, db: Db, admin: Admin) -> UserOut:
    try:
        created = create_user(db, new)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    detail = {"email": new.email, "role": new.role}  # never the password
    audit(db, admin, "user.created", target=("user", created["user_id"]), detail=detail)
    return created


@router.get("/users")
def list_users(db: Db, admin: Admin) -> list[UserOut]:
    return db.execute(
        "select user_id, email, name, role, created_at from app.users order by user_id"
    ).fetchall()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m apps.api.users")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="add a user, for example the first admin")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=["viewer", "csm", "admin"], default="admin")
    args = parser.parse_args(argv)

    password = getpass.getpass(f"Password for {args.email} (at least {MIN_PASSWORD} characters): ")
    if getpass.getpass("Repeat it: ") != password:
        parser.error("the two passwords differ")
    try:
        new = UserIn(email=args.email, name=args.name, role=args.role, password=password)
    except ValueError as error:
        parser.error(str(error))

    migrate()  # works on a fresh database, before the API has ever started
    with connect() as db:
        try:
            created = create_user(db, new)
        except ValueError as error:
            parser.error(str(error))
        # A command-line user has no actor: it is run by whoever can reach the server.
        audit(
            db,
            {"user_id": None},
            "user.created",
            target=("user", created["user_id"]),
            detail={"email": new.email, "role": new.role, "via": "command line"},
        )
    print(f"Created {created['role']} {created['email']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
