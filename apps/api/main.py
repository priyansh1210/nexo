import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from apps.api import auth, routes
from apps.api.db import SCHEMA_SQL, connect


@asynccontextmanager
async def lifespan(app: FastAPI):
    with connect() as db:
        db.execute(SCHEMA_SQL)
        if os.environ.get("NEXO_DEMO_USERS") == "1":  # never set this outside a demo
            auth.seed_demo_users(db)
    yield


app = FastAPI(title="Nexo API", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(routes.router)


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
