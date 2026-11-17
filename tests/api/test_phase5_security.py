"""Integration coverage for API authorization, tenant scope, and abuse controls."""

import pytest
from fastapi.testclient import TestClient

from apps.api.api.db.models import Base
from apps.api.api.db.session import engine
from apps.api.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_AUTH_REQUIRED", "true")
    monkeypatch.setenv("API_READ_KEY", "read-secret")
    monkeypatch.setenv("API_WRITE_KEY", "write-secret")
    monkeypatch.setenv("API_ADMIN_KEY", "admin-secret")
    monkeypatch.setenv("API_READ_FEDERATIONS", "tenant-a")
    monkeypatch.setenv("API_WRITE_FEDERATIONS", "tenant-a")
    monkeypatch.setenv("API_RATE_LIMIT", "100/minute")
    return TestClient(app)


@pytest.fixture(autouse=True)
def database():
    Base.metadata.create_all(bind=engine)
    yield


def test_protected_routes_require_authentication(client):
    response = client.get("/federations/")
    assert response.status_code == 401


def test_role_and_tenant_scope_are_enforced(client):
    assert client.post("/federations/", json={"id": "tenant-a", "name": "A"}).status_code == 401
    response = client.get(
        "/rounds/federation/tenant-b",
        headers={"Authorization": "Bearer read-secret"},
    )
    assert response.status_code == 404


def test_body_tenant_ids_are_checked_against_authenticated_scope(client):
    admin = {"Authorization": "Bearer admin-secret"}
    assert client.post(
        "/federations/",
        headers=admin,
        json={"id": "tenant-b", "name": "B"},
    ).status_code in {200, 409}
    response = client.post(
        "/rounds/",
        headers={"Authorization": "Bearer write-secret"},
        json={"federation_id": "tenant-b", "round_number": 1},
    )
    assert response.status_code == 404


def test_admin_only_blockchain_and_status_operations(client):
    assert (
        client.get(
            "/blockchain/transactions",
            headers={"Authorization": "Bearer read-secret"},
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/blockchain/transactions",
            headers={"Authorization": "Bearer admin-secret"},
        ).status_code
        != 401
    )


def test_rate_limit_returns_retry_after(monkeypatch):
    monkeypatch.setenv("API_RATE_LIMIT", "1/minute")
    from fastapi import FastAPI

    from apps.api.api.middleware.security import GlobalRateLimitMiddleware

    isolated = FastAPI()
    isolated.add_middleware(GlobalRateLimitMiddleware)

    @isolated.get("/limited")
    def limited_endpoint():
        return {"ok": True}

    isolated_client = TestClient(isolated)
    assert isolated_client.get("/limited").status_code != 429
    limited = isolated_client.get("/limited")
    assert limited.status_code == 429
    assert limited.headers["Retry-After"].isdigit()
