import json

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from apps.api.main import app, configured_cors_origins, global_exception_handler

client = TestClient(app)


def test_development_cors_defaults_are_localhost(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    assert configured_cors_origins() == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def test_production_cors_requires_explicit_origins(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
        configured_cors_origins()


def test_production_cors_rejects_wildcard(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")

    with pytest.raises(RuntimeError, match="Wildcard"):
        configured_cors_origins()


def test_cors_allows_configured_development_origin_and_rejects_other_origins():
    allowed = client.options(
        "/health/",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    rejected = client.options(
        "/health/",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in rejected.headers


@pytest.mark.asyncio
async def test_unexpected_exception_response_is_generic():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/secret",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    response = await global_exception_handler(request, RuntimeError("password=/secret"))

    assert response.status_code == 500
    assert json.loads(response.body)["message"] == "An internal server error occurred."
    assert "password" not in response.body.decode()
