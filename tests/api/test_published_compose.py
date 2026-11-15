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
    assert "${BLOCKCHAIN_CONTRACTS_DIR:?BLOCKCHAIN_CONTRACTS_DIR must point to a directory containing contracts.json}" in compose
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
