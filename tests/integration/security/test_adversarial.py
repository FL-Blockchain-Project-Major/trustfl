import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api.api.db.session import engine, Base

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    # Setup baseline federation/round for testing
    client.post("/federations/", json={"id": "sec_fed_1", "name": "Sec", "min_clients": 2, "max_rounds": 10})
    client.post("/clients/", json={"id": "sec_client_1", "federation_id": "sec_fed_1", "public_key_b64": "key"})
    client.post("/rounds/", json={"federation_id": "sec_fed_1", "round_number": 1})
    yield
    Base.metadata.drop_all(bind=engine)

def test_duplicate_submission():
    payload = {
        "id": "upd_sec_1",
        "round_id": "sec_fed_1_round1",
        "client_id": "sec_client_1",
        "nonce": "nonce_sec_1"
    }
    r1 = client.post("/updates/", json=payload)
    assert r1.status_code == 200
    
    # Exact duplicate ID
    r2 = client.post("/updates/", json=payload)
    assert r2.status_code == 409

    # Same client, same round, different ID
    payload2 = {
        "id": "upd_sec_2",
        "round_id": "sec_fed_1_round1",
        "client_id": "sec_client_1",
        "nonce": "nonce_sec_2"
    }
    r3 = client.post("/updates/", json=payload2)
    assert r3.status_code == 400
    assert "Client already submitted" in r3.json()["message"]

def test_replay_attack_nonce():
    # Setup a new client
    client.post("/clients/", json={"id": "sec_client_2", "federation_id": "sec_fed_1", "public_key_b64": "key2"})
    
    # Client 2 tries to reuse nonce from client 1
    payload = {
        "id": "upd_sec_3",
        "round_id": "sec_fed_1_round1",
        "client_id": "sec_client_2",
        "nonce": "nonce_sec_1" # reused nonce
    }
    r = client.post("/updates/", json=payload)
    assert r.status_code == 400
    assert "Nonce already used" in r.json()["message"]

def test_oversized_payload():
    payload = {
        "id": "upd_sec_4",
        "round_id": "sec_fed_1_round1",
        "client_id": "sec_client_2",
        "nonce": "A" * 150 # exceeds 128 chars limit
    }
    r = client.post("/updates/", json=payload)
    assert r.status_code == 422 # Validation error
