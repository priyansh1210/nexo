from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.api.auth import DEMO_PASSWORD
from apps.api.main import app


def sign_in_with(email: str, password: str) -> TestClient:
    client = TestClient(app)
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return client


def sign_in(email: str) -> TestClient:
    return sign_in_with(email, DEMO_PASSWORD)


@pytest.fixture(scope="module")
def api(warehouse, request):
    """The API over a private copy of the built warehouse, one copy per test module."""
    copy = warehouse.copy(request.module.__name__.rpartition(".")[2])
    with pytest.MonkeyPatch.context() as env:
        env.setenv("DATABASE_URL", copy.url)
        env.setenv("NEXO_DEMO_USERS", "1")
        with TestClient(app) as anonymous:  # entering runs startup: migrations and demo users
            yield SimpleNamespace(
                anonymous=anonymous,
                viewer=sign_in("viewer@nexo.example"),
                csm=sign_in("maya.okafor@nexo.example"),
                admin=sign_in("admin@nexo.example"),
                sign_in=sign_in,
                sign_in_with=sign_in_with,
                url=copy.url,
                data=warehouse.data,
                today=warehouse.today,
            )
