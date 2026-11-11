"""The evaluation scenarios, run with the mock provider on copies of the seeded warehouse."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from apps.api.agent.providers import MockProvider
from apps.api.auth import seed_demo_users
from apps.api.db import migrate
from evals import runner
from services.mock_sources.main import create_app


@pytest.mark.parametrize("scenario", runner.SCENARIOS, ids=lambda s: s["name"])
def test_scenario(scenario, warehouse, monkeypatch):
    copy = warehouse.copy(f"eval_{scenario['name']}")
    monkeypatch.setenv("DATABASE_URL", copy.url)
    migrate()  # the application tables: users, proposals, outbox, audit
    with psycopg.connect(copy.url) as conn:
        seed_demo_users(conn)
    sources = TestClient(create_app(warehouse.data))
    assert runner.run(copy.url, scenario, MockProvider(), sources) == []
