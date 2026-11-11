import os
from contextlib import asynccontextmanager

import httpx
import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from apps.api import actions, auth, ingest, routes, users
from apps.api.agent import routes as chat
from apps.api.db import connect, migrate
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
    with chat.agent_runtime() as runtime, httpx.Client(base_url=sources, timeout=5) as client:
        app.state.agent, app.state.sources = runtime, client
        yield


app = FastAPI(title="Nexo API", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(routes.router)
app.include_router(ingest.router)
app.include_router(users.router)
app.include_router(chat.router)
app.include_router(actions.router)


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
