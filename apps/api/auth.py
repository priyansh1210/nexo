"""Sign-in, sessions and roles.

A session is a random token in an HTTP-only cookie; the database keeps only its hash. Roles are
ordered: a csm can do everything a viewer can, and an admin everything a csm can.
"""

import hashlib
import hmac
import os
import secrets
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from apps.api.db import Db, audit, connect

SESSION_COOKIE = "nexo_session"
SESSION_DAYS = 7
ROLES = ("viewer", "csm", "admin")
# Sign-in rate limit: this many failed attempts for one email within the window blocks further
# attempts for that email until the oldest one leaves the window.
MAX_FAILED_LOGINS = 5
LOGIN_WINDOW_MINUTES = 15
DEMO_PASSWORD = "nexo-demo"

router = APIRouter(prefix="/auth", tags=["auth"])


class User(BaseModel):
    user_id: int
    email: str
    name: str
    role: str


class Login(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)  # bounds the hashing work one request can cause


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt = bytes.fromhex(stored.partition("$")[0])
    return hmac.compare_digest(hash_password(password, salt), stored)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request, db: Db) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    user = (
        token
        and db.execute(
            "select u.user_id, u.email, u.name, u.role from app.sessions s "
            "join app.users u using (user_id) where s.token_hash = %s and s.expires_at > now()",
            (_token_hash(token),),
        ).fetchone()
    )
    if not user:
        raise HTTPException(401, "Sign in first")
    return user


def require(role: str):
    """A dependency that lets the request through only for this role or a higher one."""

    def check(user: Annotated[dict, Depends(current_user)]) -> dict:
        if ROLES.index(user["role"]) < ROLES.index(role):
            raise HTTPException(
                403, f"This needs the {role} role; you are signed in as {user['role']}"
            )
        return user

    return check


Viewer = Annotated[dict, Depends(require("viewer"))]
Csm = Annotated[dict, Depends(require("csm"))]
Admin = Annotated[dict, Depends(require("admin"))]

# Hashing this for an unknown email makes a wrong email take as long as a wrong password.
_NO_SUCH_USER = hash_password(secrets.token_hex(8))


def _record_failed_login(email: str) -> None:
    # Its own connection: the request's transaction is rolled back when the sign-in fails.
    with connect() as db:
        db.execute("insert into app.login_attempts (email) values (%s)", (email,))
        db.execute(
            "delete from app.login_attempts where at < now() - make_interval(mins => %s)",
            (LOGIN_WINDOW_MINUTES,),
        )


@router.post("/login")
def login(credentials: Login, response: Response, db: Db) -> User:
    email = credentials.email.strip().lower()
    # Attempts for one email run one at a time, so parallel guesses each see the earlier failures.
    # The lock is released when this request's transaction ends.
    db.execute("select pg_advisory_xact_lock(hashtext('login:' || %s))", (email,))
    # Checked before the password hash, so a blocked attacker cannot make the server hash.
    # shortcut: limited per email only, because behind the Compose network every request comes from
    # one address; add a per-client limit once a proxy passes the real client address.
    retry_after = db.execute(
        "select ceil(extract(epoch from min(at) + make_interval(mins => %(window)s) - now()))::int "
        "as seconds "
        "from app.login_attempts where email = %(email)s "
        "and at > now() - make_interval(mins => %(window)s) having count(*) >= %(max)s",
        {"email": email, "window": LOGIN_WINDOW_MINUTES, "max": MAX_FAILED_LOGINS},
    ).fetchone()
    if retry_after:
        seconds = max(retry_after["seconds"], 1)
        raise HTTPException(
            429,
            f"Too many failed sign-ins for this email. Try again in {seconds} seconds.",
            headers={"Retry-After": str(seconds)},
        )

    user = db.execute(
        "select user_id, email, name, role, password_hash from app.users where email = %s",
        (email,),
    ).fetchone()
    if (
        not verify_password(credentials.password, user["password_hash"] if user else _NO_SUCH_USER)
        or not user
    ):
        _record_failed_login(email)
        raise HTTPException(401, "Wrong email or password")

    db.execute("delete from app.login_attempts where email = %s", (email,))
    token = secrets.token_urlsafe(32)
    db.execute(
        "insert into app.sessions (token_hash, user_id, expires_at) "
        "values (%s, %s, now() + make_interval(days => %s))",
        (_token_hash(token), user["user_id"], SESSION_DAYS),
    )
    audit(db, user, "auth.login")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",  # the browser will not send it on a cross-site POST
        secure=os.environ.get("NEXO_COOKIE_SECURE") == "1",  # set to 1 when served over HTTPS
    )
    return User(**user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Db) -> None:
    if token := request.cookies.get(SESSION_COOKIE):
        db.execute("delete from app.sessions where token_hash = %s", (_token_hash(token),))
    response.delete_cookie(SESSION_COOKIE)


@router.get("/me")
def me(user: Viewer) -> User:
    return User(**user)


def seed_demo_users(db: psycopg.Connection) -> None:
    """The demo's sign-ins: the four account owners as csm, plus one admin and one viewer."""
    from data.synthetic.generate import OWNERS  # demo-only dependency, so it is imported on use

    people = [(email, name, "csm") for name, email in OWNERS]
    people += [
        ("admin@nexo.example", "Demo Admin", "admin"),
        ("viewer@nexo.example", "Demo Viewer", "viewer"),
    ]
    for email, name, role in people:
        db.execute(
            "insert into app.users (email, name, role, password_hash) values (%s, %s, %s, %s) "
            "on conflict (email) do nothing",
            (email, name, role, hash_password(DEMO_PASSWORD)),
        )
