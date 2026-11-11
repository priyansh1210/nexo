import os
from contextlib import asynccontextmanager

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from apps.api import actions, auth, ingest, routes, users
from apps.api.agent import routes as chat
from apps.api.db import connect, migrate, open_pool
from data.landing import ensure_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate()
    with connect() as db:
        ensure_schema(db)  # the ingest routes write to raw and meta
        if os.environ.get("NEXO_DEMO_USERS") == "1":  # never set this outside a demo
            auth.seed_demo_users(db)
    # The live source systems, re-read just before an approved action runs.
    sources = os.environ.get("MOCK_SOURCES_URL", "http://localhost:8001")
    with (
        open_pool() as pool,
        chat.agent_runtime() as runtime,
        httpx.Client(base_url=sources, timeout=5) as client,
    ):
        app.state.pool, app.state.agent, app.state.sources = pool, runtime, client
        yield


# The largest push is a 5 MB CSV, or 5,000 events; this leaves room to spare.
MAX_BODY_BYTES = 10 * 1024 * 1024


class BodyLimit:
    """Refuses a request body over the limit while it streams in, before it can fill memory."""

    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        too_large = f"The request body is larger than {self.limit // (1024 * 1024)} MB"
        declared = dict(scope["headers"]).get(b"content-length")
        if declared and int(declared) > self.limit:
            return await JSONResponse({"detail": too_large}, 413)(scope, receive, send)
        received = 0

        async def counted():  # a body sent in chunks declares no length, so count what arrives
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > self.limit:
                raise HTTPException(413, too_large)
            return message

        await self.app(scope, counted, send)


app = FastAPI(title="Nexo API", lifespan=lifespan)
app.add_middleware(BodyLimit, limit=MAX_BODY_BYTES)
app.include_router(auth.router)
app.include_router(routes.router)
app.include_router(ingest.router)
app.include_router(users.router)
app.include_router(chat.router)
app.include_router(actions.router)


@app.exception_handler(PoolTimeout)
def busy(request: Request, error: PoolTimeout) -> JSONResponse:
    # Every database connection stayed in use for 30 seconds: too many requests at once.
    detail = {"detail": "Nexo is busy. Try again in a moment."}
    return JSONResponse(detail, 503, headers={"Retry-After": "5"})


@app.exception_handler(psycopg.errors.UndefinedTable)
def warehouse_not_built(request: Request, error: psycopg.errors.UndefinedTable) -> JSONResponse:
    # The marts and meta tables appear only after the first pipeline run.
    return JSONResponse({"detail": "The warehouse is not built yet. Run the pipeline first."}, 503)


@app.get("/health")
def health() -> dict:
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=2) as conn:
            conn.execute("select 1")
        db = True
    except psycopg.Error:
        db = False
    return {"status": "ok", "db": db}
