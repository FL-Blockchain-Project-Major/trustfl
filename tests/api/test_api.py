import pytest
from fastapi.testclient import TestClient

from apps.api.api.db.models import Base
from apps.api.api.db.session import engine
from apps.api.main import app

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def test_health():
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_federation_lifecycle():
    # 1. Create Federation
    payload = {
        "id": "fed_test_1",
        "name": "Test Federation",
        "min_clients": 2,
        "max_rounds": 10
    }
    response = client.post("/federations/", json=payload)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == "fed_test_1"

    # 2. List Federations
    response = client.get("/federations/")
    assert response.status_code == 200
    assert len(response.json()["data"]) >= 1

    # 3. Register Client
    client_payload = {
        "id": "client_1",
        "federation_id": "fed_test_1",
        "public_key_b64": "pubkey_b64_string",
        "capabilities": {"gpu": True}
    }
    response = client.post("/clients/", json=client_payload)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == "client_1"

    # 4. Create Round
    round_payload = {
        "federation_id": "fed_test_1",
        "round_number": 1,
        "model_version": "v1.0"
    }
    response = client.post("/rounds/", json=round_payload)
    assert response.status_code == 200
    round_id = response.json()["data"]["id"]
    assert round_id == "fed_test_1_round1"

    # 5. Submit Update
    update_payload = {
        "id": "update_1",
        "round_id": round_id,
        "client_id": "client_1",
        "artifact_hash": "hash_123",
        "nonce": "nonce_123"
    }
    response = client.post("/updates/", json=update_payload)
    assert response.status_code == 200

    # 6. Submit Proof
    proof_payload = {
        "id": "proof_1",
        "update_id": "update_1",
        "client_id": "client_1",
        "federation_id": "fed_test_1",
        "round_id": round_id,
        "public_commitment": "commit_123"
    }
    response = client.post("/proofs/", json=proof_payload)
    assert response.status_code == 200
    proof_id = response.json()["data"]["id"]
    response = client.get(f"/proofs/{proof_id}")
    assert response.status_code == 200
    assert response.json()["data"]["update_id"] == "update_1"
    assert client.get("/proofs/missing-proof").status_code == 404

    artifact_payload = {
        "id": "artifact_1",
        "federation_id": "fed_test_1",
        "round_number": 1,
        "client_id": "client_1",
        "uri": "ipfs://artifact-1",
        "sha256_hash": "sha256:" + "a" * 64,
        "model_version": "v1.0",
    }
    response = client.post("/artifacts/", json=artifact_payload)
    assert response.status_code == 200
    response = client.get("/artifacts/artifact_1")
    assert response.status_code == 200
    assert response.json()["data"]["uri"] == "ipfs://artifact-1"
    assert client.get("/artifacts/missing-artifact").status_code == 404

    # 7. Record Blockchain Tx
    tx_payload = {
        "id": "tx_1",
        "contract_name": "UpdateRegistry",
        "function_name": "submitUpdate"
    }
    response = client.post("/blockchain/transactions", json=tx_payload)
    assert response.status_code == 200
    response = client.post(
        "/blockchain/transactions",
        json={**tx_payload, "tx_hash": "0x" + "1" * 64, "status": "CONFIRMED"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["id"] == "tx_1"
    assert response.json()["data"]["status"] == "CONFIRMED"
