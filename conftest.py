"""Shared test database: one Postgres container per test run, with the warehouse built once.

Loading the synthetic data and building the warehouse takes about a minute, so it is done once,
into a template database. Each test module then takes its own copy, which takes a second, and is
free to change it.
"""

import shutil
from datetime import UTC, datetime
from types import SimpleNamespace

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from testcontainers.community.postgres import PostgresContainer

from data.pipelines import runner
from data.synthetic.generate import generate, write
from services.mock_sources.main import create_app


@pytest.fixture(scope="session")
def warehouse(tmp_path_factory):
    # The database runs in UTC, so "today" must be the UTC date too.
    today = datetime.now(UTC).date()
    data = generate(seed=7, as_of=today)
    source_dir = tmp_path_factory.mktemp("sources")
    write(data, source_dir)

    with (
        PostgresContainer("pgvector/pgvector:pg16", driver=None) as postgres,
        pytest.MonkeyPatch.context() as env,
    ):
        template_url = postgres.get_connection_url()
        server_url = template_url.rsplit("/", 1)[0]
        env.setenv("DATABASE_URL", template_url)
        with runner.connect() as conn:
            sources = runner.connectors(source_dir, TestClient(create_app(data)))
            first_sync, first_build = runner.sync(conn, sources), runner.build(conn)

        def copy(name: str) -> SimpleNamespace:
            """A private copy of the built database and of the source files."""
            with psycopg.connect(f"{server_url}/postgres", autocommit=True) as admin:
                admin.execute(
                    sql.SQL("create database {} template test").format(sql.Identifier(name))
                )
            data_dir = tmp_path_factory.mktemp(name)
            shutil.copytree(source_dir, data_dir, dirs_exist_ok=True)
            return SimpleNamespace(url=f"{server_url}/{name}", data_dir=data_dir)

        yield SimpleNamespace(
            today=today, data=data, first_sync=first_sync, first_build=first_build, copy=copy
        )
