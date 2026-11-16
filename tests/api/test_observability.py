import json

from fastapi.testclient import TestClient
from trustfl_observability import metrics

from apps.api.main import app

client = TestClient(app)


def test_metrics_endpoint_emits_api_request_and_latency_metrics():
    metrics.reset()
    response = client.get("/health/live", headers={"traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01"})

    assert response.status_code == 200
    assert response.headers["Traceparent"].startswith("00-" + "a" * 32 + "-")
    rendered = client.get("/metrics").text
    assert "trustfl_api_requests_total" in rendered
    assert "trustfl_api_request_duration_seconds_count" in rendered


def test_readiness_is_safe_and_has_no_dependency_details():
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] in {"ready", "degraded"}
    assert "DATABASE_URL" not in json.dumps(response.json())
