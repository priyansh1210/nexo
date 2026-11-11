import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from apps.api import auth, ingest, routes, users
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
    with chat.agent_runtime() as runtime:
        app.state.agent = runtime
        yield


app = FastAPI(title="Nexo API", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(routes.router)
app.include_router(ingest.router)
app.include_router(users.router)
app.include_router(chat.router)


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
