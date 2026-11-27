from pathlib import Path

PUBLISHED_COMPOSE = Path(__file__).parents[2] / "docker-compose.published.yml"


def test_published_compose_is_fail_closed_for_production():
    compose = PUBLISHED_COMPOSE.read_text()

    assert "ENVIRONMENT=production" in compose
    assert "${TRUSTFL_VERSION:?TRUSTFL_VERSION must be set to a pinned release}" in compose
    assert "${API_READ_KEY:?API_READ_KEY must be set}" in compose
    assert "${API_WRITE_KEY:?API_WRITE_KEY must be set}" in compose
    assert "${API_ADMIN_KEY:?API_ADMIN_KEY must be set}" in compose
    assert "${COORDINATOR_PRIVATE_KEY:?COORDINATOR_PRIVATE_KEY must be set}" in compose
    assert "${COORDINATOR_ENROLLMENT_TOKEN:?COORDINATOR_ENROLLMENT_TOKEN must be set}" in compose
    assert "${BLOCKCHAIN_RPC_URL:?BLOCKCHAIN_RPC_URL must be set}" in compose
    assert (
        "${BLOCKCHAIN_CONTRACTS_DIR:?BLOCKCHAIN_CONTRACTS_DIR must point to a directory containing contracts.json}"
        in compose
    )
    assert "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}" in compose
    assert "${CORS_ALLOWED_ORIGINS:?CORS_ALLOWED_ORIGINS must be set}" in compose
    assert "${FL_DATASET_DIR:?FL_DATASET_DIR must point to the client dataset}" in compose


def test_published_compose_does_not_provision_development_blockchain():
    compose = PUBLISHED_COMPOSE.read_text()

    assert "\n  hardhat:\n" not in compose
    assert "\n  contract-deployer:\n" not in compose
    assert "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80" not in compose
    assert "trustfl-read-dev" not in compose
    assert "trustfl-write-dev" not in compose
    assert "trustfl-admin-dev" not in compose


def test_published_compose_provisions_zkp_artifacts_for_api_and_coordinator():
    import yaml

    data = yaml.safe_load(PUBLISHED_COMPOSE.read_text())
    services = data["services"]
    api_svc = services["api"]
    coord_svc = services["coordinator"]

    api_env = "\n".join(api_svc["environment"])
    coord_env = "\n".join(coord_svc["environment"])
    assert "ZKP_ARTIFACTS_DIR=/zkp-artifacts" in api_env
    assert "ZKP_ARTIFACTS_DIR=/zkp-artifacts" in coord_env
    assert "ZKP_VERIFY_COMMAND=node /app/packages/zkp/src/verify-cli.js" in api_env
    assert "ZKP_VERIFY_COMMAND=node /app/packages/zkp/src/verify-cli.js" in coord_env

    expected_mount = "${ZKP_ARTIFACTS_DIR:?ZKP_ARTIFACTS_DIR must contain the pinned ZKP artifacts}:/zkp-artifacts:ro"
    assert expected_mount in api_svc.get("volumes", [])
    assert expected_mount in coord_svc.get("volumes", [])
    assert "/health/ready" in " ".join(api_svc["healthcheck"]["test"])


def test_api_zkp_readiness_fails_closed_when_artifacts_missing(monkeypatch, tmp_path):
    from apps.api.api.routers import health

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ZKP_VERIFY_COMMAND", "node /app/packages/zkp/src/verify-cli.js")
    monkeypatch.delenv("ZKP_ARTIFACTS_DIR", raising=False)
    assert health._zkp_ready() is False

    # Missing verification_key.json must fail closed
    empty_dir = tmp_path / "empty_zkp"
    empty_dir.mkdir()
    monkeypatch.setenv("ZKP_ARTIFACTS_DIR", str(empty_dir))
    assert health._zkp_ready() is False

    # Missing ZKP_VERIFY_COMMAND must fail closed even when key exists
    (empty_dir / "verification_key.json").write_text("{}")
    monkeypatch.delenv("ZKP_VERIFY_COMMAND", raising=False)
    assert health._zkp_ready() is False

    # Both present -> ready
    monkeypatch.setenv("ZKP_VERIFY_COMMAND", "node /app/packages/zkp/src/verify-cli.js")
    assert health._zkp_ready() is True
