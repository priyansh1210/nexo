import os

import psycopg
from fastapi import FastAPI

app = FastAPI(title="Nexo API")


@app.get("/health")
def health() -> dict:
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=2) as conn:
            conn.execute("select 1")
        db = True
    except psycopg.Error:
        db = False
    return {"status": "ok", "db": db}
