#!/usr/bin/env python3
"""
TrustFL API endpoint test using FastAPI TestClient (in-process, no network).
Tests all major endpoints: health, auth, federation, client, round, update,
artifact, blockchain, proof — including valid/invalid/missing/duplicate cases.
"""
import sys, json, os

# Ensure DATABASE_URL uses SQLite so we don't need Postgres running
os.environ.setdefault("DATABASE_URL", "sqlite:///./scratch_test.db")

sys.path.insert(0, "/home/sayam/Desktop/TrustFL/packages/schemas")
sys.path.insert(0, "/home/sayam/Desktop/TrustFL/packages/crypto")
sys.path.insert(0, "/home/sayam/Desktop/TrustFL/packages/storage")
sys.path.insert(0, "/home/sayam/Desktop/TrustFL/packages/fl_core")
sys.path.insert(0, "/home/sayam/Desktop/TrustFL/packages/ml_core")
sys.path.insert(0, "/home/sayam/Desktop/TrustFL/packages/blockchain")
sys.path.insert(0, "/home/sayam/Desktop/TrustFL")

from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api.api.db.session import engine
from apps.api.api.db.models import Base

# Create tables
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

client = TestClient(app)

PASS = []
FAIL = []

def check(name, r, expected_statuses, check_body=None):
    status_ok = r.status_code in expected_statuses
    body_ok = True
    body_err = None
    if check_body:
        try:
            body = r.json()
            for key, expected_val in check_body.items():
                if key not in body:
                    body_ok = False
                    body_err = f"Missing key '{key}' in response"
                elif expected_val is not None and body[key] != expected_val:
                    body_ok = False
                    body_err = f"Key '{key}': expected {expected_val!r}, got {body[key]!r}"
        except Exception as e:
            body_ok = False
            body_err = f"JSON parse error: {e}"

    if status_ok and body_ok:
        PASS.append(name)
        print(f"  PASS  [{r.status_code}] {name}")
    else:
        reason = f"status={r.status_code} (expected {expected_statuses})"
        if body_err:
            reason += f"; body: {body_err}"
        FAIL.append((name, reason, r.text[:200]))
        print(f"  FAIL  [{r.status_code}] {name} — {reason}")
    return r

print("\n===== HEALTH =====")
r = check("GET /health — valid", client.get("/health"), [200])
print("  Body:", r.text[:100])

print("\n===== AUTH (no auth configured — verify open access) =====")
r = check("POST /federations/ — no auth header accepted", client.post("/federations/", json={
    "id": "fed_auth_test", "name": "Auth Test", "min_clients": 2, "max_rounds": 5
}), [200, 201])

print("\n===== FEDERATIONS =====")
fed_payload = {"id": "fed_001", "name": "FL Federation 1", "min_clients": 2, "max_rounds": 10}

r = check("POST /federations/ — valid creation", client.post("/federations/", json=fed_payload), [200, 201])
print("  Body:", r.text[:100])

r = check("POST /federations/ — duplicate ID (409)", client.post("/federations/", json=fed_payload), [409])

r = check("POST /federations/ — missing required 'id' field (422)", client.post("/federations/", json={
    "name": "No ID Federation"
}), [422])

r = check("GET /federations/ — list", client.get("/federations/"), [200])
body = r.json()
feds = body.get("data", body)  # APIResponse wraps in {"success": ..., "data": [...]}
assert isinstance(feds, list), f"Expected list in data, got: {feds}"
check("GET /federations/ — returns list schema", r, [200])

r = check("GET /federations/fed_001 — valid get", client.get("/federations/fed_001"), [200])
check("GET /federations/missing_id — 404", client.get("/federations/missing_id"), [404])

print("\n===== CLIENTS =====")
client_payload = {
    "id": "client_001",
    "federation_id": "fed_001",
    "public_key_b64": "dGVzdHB1YmxpY2tleQ=="
}
r = check("POST /clients/ — valid registration", client.post("/clients/", json=client_payload), [200, 201])
print("  Body:", r.text[:100])

r = check("POST /clients/ — duplicate client (409)", client.post("/clients/", json=client_payload), [409])

r = check("POST /clients/ — nonexistent federation (404)", client.post("/clients/", json={
    "id": "client_orphan",
    "federation_id": "nonexistent_fed",
    "public_key_b64": "dGVzdA=="
}), [404])

r = check("POST /clients/ — missing required fields (422)", client.post("/clients/", json={
    "id": "client_bad"
}), [422])

r = check("GET /clients/client_001 — valid get", client.get("/clients/client_001"), [200])
r = check("GET /clients/missing — 404", client.get("/clients/missing"), [404])
r = check("GET /clients/ — list by federation", client.get("/clients/", params={"federation_id": "fed_001"}), [200])

print("\n===== ROUNDS =====")
round_payload = {"federation_id": "fed_001", "round_number": 1}

r = check("POST /rounds/ — valid creation", client.post("/rounds/", json=round_payload), [200, 201])
print("  Body:", r.text[:100])

r = check("POST /rounds/ — duplicate round (409)", client.post("/rounds/", json=round_payload), [409])

r = check("POST /rounds/ — missing federation (404)", client.post("/rounds/", json={
    "federation_id": "nonexistent", "round_number": 1
}), [404])

r = check("POST /rounds/ — missing required fields (422)", client.post("/rounds/", json={}), [422])

r = check("GET /rounds/fed_001_round1 — valid get", client.get("/rounds/fed_001_round1"), [200])
r = check("GET /rounds/missing — 404", client.get("/rounds/missing"), [404])

print("\n===== UPDATES =====")
update_payload = {
    "id": "upd_001",
    "round_id": "fed_001_round1",
    "client_id": "client_001",
    "nonce": "nonce_abc_001"
}
r = check("POST /updates/ — valid submission", client.post("/updates/", json=update_payload), [200, 201])
print("  Body:", r.text[:100])

r = check("POST /updates/ — duplicate update ID (409)", client.post("/updates/", json=update_payload), [409])

r = check("POST /updates/ — same client/round, different ID (400 — duplicate client)", client.post("/updates/", json={
    "id": "upd_002",
    "round_id": "fed_001_round1",
    "client_id": "client_001",
    "nonce": "nonce_abc_002"
}), [400])

r = check("POST /updates/ — nonce replay by new client (400)", 
    client.post("/clients/", json={"id": "client_002", "federation_id": "fed_001", "public_key_b64": "dGVzdA=="}),
    [200, 201])
r = check("POST /updates/ — nonce replay (400)", client.post("/updates/", json={
    "id": "upd_003",
    "round_id": "fed_001_round1",
    "client_id": "client_002",
    "nonce": "nonce_abc_001"  # reused nonce
}), [400])

r = check("POST /updates/ — oversized nonce (422)", client.post("/updates/", json={
    "id": "upd_oversized",
    "round_id": "fed_001_round1",
    "client_id": "client_002",
    "nonce": "X" * 150
}), [422])

r = check("POST /updates/ — missing required fields (422)", client.post("/updates/", json={}), [422])

r = check("GET /updates/upd_001 — valid get", client.get("/updates/upd_001"), [200])
r = check("GET /updates/missing — 404", client.get("/updates/missing"), [404])

print("\n===== ARTIFACTS =====")
r = check("GET /artifacts/ — list", client.get("/artifacts/"), [200])
r = check("GET /artifacts/missing — 404", client.get("/artifacts/missing"), [404])

artifact_payload = {
    "id": "art_001",
    "federation_id": "fed_001",
    "uri": "ipfs://QmTestHash",
    "sha256_hash": "abc123"
}
r = check("POST /artifacts/ — valid creation", client.post("/artifacts/", json=artifact_payload), [200, 201])
print("  Body:", r.text[:100])
r = check("GET /artifacts/art_001 — valid get", client.get("/artifacts/art_001"), [200])

print("\n===== PROOFS =====")
r = check("GET /proofs/ — list", client.get("/proofs/"), [200])
r = check("GET /proofs/missing — 404", client.get("/proofs/missing"), [404])

proof_payload = {
    "id": "proof_001",
    "update_id": "upd_001",
    "client_id": "client_001",
    "federation_id": "fed_001",
    "round_id": "fed_001_round1",
    "public_commitment": "commitment_hash_abc",
    "protocol": "poseidon_commitment_v1"
}
r = check("POST /proofs/ — valid submission", client.post("/proofs/", json=proof_payload), [200, 201])
print("  Body:", r.text[:100])
r = check("GET /proofs/proof_001 — valid get", client.get("/proofs/proof_001"), [200])

print("\n===== BLOCKCHAIN TRANSACTIONS =====")
r = check("GET /blockchain/ — list", client.get("/blockchain/"), [200])
r = check("GET /blockchain/missing — 404", client.get("/blockchain/missing"), [404])

# POST a blockchain tx record
bctx_payload = {
    "id": "tx_001",
    "contract_name": "UpdateRegistry",
    "function_name": "submitUpdate",
    "entity_id": "upd_001",
    "entity_type": "update",
    "status": "CONFIRMED"
}
r = check("POST /blockchain/ — valid creation", client.post("/blockchain/", json=bctx_payload), [200, 201])
print("  Body:", r.text[:100])
r = check("GET /blockchain/tx_001 — valid get", client.get("/blockchain/tx_001"), [200])

print("\n===== ERROR HANDLING =====")
r = check("GET /nonexistent_route — 404 or 422", client.get("/completely_missing_endpoint"), [404, 422, 405])
r = check("POST /federations/ — malformed JSON (422)", client.post(
    "/federations/",
    content='{"id": "broken",}',
    headers={"Content-Type": "application/json"}
), [422])

# Summary
print(f"\n{'='*50}")
print(f"TESTS EXECUTED : {len(PASS) + len(FAIL)}")
print(f"PASSED         : {len(PASS)}")
print(f"FAILED         : {len(FAIL)}")
if FAIL:
    print("\nFAILED TESTS:")
    for name, reason, body in FAIL:
        print(f"  - {name}: {reason}")
        print(f"    Response: {body}")

# Cleanup
Base.metadata.drop_all(bind=engine)
import os as _os
try: _os.remove("scratch_test.db")
except: pass
