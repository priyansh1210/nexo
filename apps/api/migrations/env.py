"""Alembic environment: where the migrations in `versions/` run.

The database comes from DATABASE_URL. Migrations are written as plain SQL with `op.execute`.
"""

import os

from alembic import context
from sqlalchemy import create_engine, pool, text

url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
# NullPool closes the connection at the end, which is what releases the lock taken below.
engine = create_engine(url, poolclass=pool.NullPool)

with engine.connect() as connection:
    # One migration run at a time, however many API processes start together.
    connection.execute(text("select pg_advisory_lock(727274)"))
    connection.execute(text("create schema if not exists app"))
    connection.commit()

    context.configure(connection=connection, version_table_schema="app")
    with context.begin_transaction():
        context.run_migrations()
