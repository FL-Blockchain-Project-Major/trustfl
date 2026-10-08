#!/usr/bin/env python3
"""
TrustFL Complete End-to-End Workflow Test
Executes every transition in sequence; halts at first failure.

Steps:
  0.  Dashboard reachability
  1.  API health
  2.  Create federation via API
  3.  Register clients via API
  4.  Create training round via API
  5.  Client local training (FL core)
  6.  Signed update creation (crypto)
  7.  Signature verification (coordinator-side)
  8.  Artifact storage + hash verification
  9.  Submit update to API
  10. Blockchain: register client
  11. Blockchain: create round
  12. Blockchain: submit update
  13. ZKP: generate commitment
  14. ZKP: verify commitment
  15. Aggregation (FedAvg)
  16. Global model version bump via API
  17. Round finalization via API
  18. Dashboard: check API data is reflected
"""

import sys, json, secrets, os, time, urllib.request, urllib.error, hashlib
from pathlib import Path

# Python path setup
for p in ["packages/schemas","packages/crypto","packages/storage",
          "packages/fl_core","packages/ml_core","packages/blockchain",
          "packages/zkp","."]:
    sys.path.insert(0, p)

# ── Helpers ────────────────────────────────────────────────────────────────

API = "http://127.0.0.1:8000"
DASHBOARD = "http://127.0.0.1:3000"
STEP = 0

def step(n, title):
    global STEP
    STEP = n
    print(f"\n{'='*60}")
    print(f"STEP {n}: {title}")
    print('='*60)

def ok(msg, detail=""):
    tag = f" → {detail}" if detail else ""
    print(f"  ✓ {msg}{tag}")

def fail(msg, evidence="", root_cause=""):
    print(f"\n{'!'*60}")
    print(f"  ✗ FAILURE at STEP {STEP}: {msg}")
    if evidence:
        print(f"  EVIDENCE: {evidence}")
    if root_cause:
        print(f"  ROOT CAUSE: {root_cause}")
    print(f"{'!'*60}")
    report(first_fail=f"Step {STEP}: {msg}", evidence=evidence, root_cause=root_cause)
    sys.exit(1)

def api(method, path, body=None, expect=(200,201,409)):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
                                  headers={"Content-Type":"application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            code = r.getcode()
            raw = r.read()
            parsed = json.loads(raw)
            if code not in expect:
                fail(f"API {method} {path} returned {code}", str(parsed))
            return code, parsed
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = raw.decode()
        if e.code in expect:
            return e.code, parsed
        fail(f"API {method} {path} returned HTTP {e.code}", str(parsed))
    except Exception as e:
        fail(f"API {method} {path} connection error", str(e))

def http_get_status(url):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.getcode()
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0

_workflow_steps_done = []
_first_fail = None
_fail_evidence = ""
_fail_root_cause = ""

def mark_done(label):
    _workflow_steps_done.append(f"✓ {label}")

def report(first_fail=None, evidence="", root_cause=""):
    print(f"\n{'='*60}")
    print("WORKFLOW EXECUTION REPORT")
    print('='*60)
    print("\nCompleted Steps:")
    for s in _workflow_steps_done:
        print(f"  {s}")
    if first_fail:
        print(f"\nFirst Failing Step:\n  ✗ {first_fail}")
    if evidence:
        print(f"\nEvidence:\n  {evidence}")
    if root_cause:
        print(f"\nRoot Cause:\n  {root_cause}")
    verdict = "NOT READY" if first_fail else "READY"
    print(f"\nFINAL VERDICT: {verdict}")
    print('='*60)

# ── Workflow ───────────────────────────────────────────────────────────────

def main():
    print("="*60)
    print("TrustFL Complete End-to-End Workflow Test")
    print(f"Time: {time.strftime('%Y-%m-%dT%H:%M:%S')}")
    print("="*60)

    # ── Step 0: Dashboard reachability ────────────────────────────
    step(0, "Dashboard reachability")
    dash_code = http_get_status(DASHBOARD)
    if dash_code == 0:
        fail("Dashboard not reachable at http://127.0.0.1:3000",
             "Connection refused",
             "Next.js dev server is not running")
    # 500 is the known defect (empty layout.tsx) — dashboard process is alive
    ok(f"Dashboard server running", f"HTTP {dash_code}")
    if dash_code == 500:
        ok("Known defect: app/layout.tsx is empty (0 bytes) → Next.js cannot render any route",
           "Recorded, not a blocker for backend workflow")
    mark_done("Dashboard: server process running (HTTP 500 — empty layout.tsx defect)")

    # ── Step 1: API health ─────────────────────────────────────────
    step(1, "API health")
    code, resp = api("GET", "/federations/")
    ok("API reachable", f"HTTP {code}, federations in db: {len(resp.get('data',[]))}")
    mark_done("API health: reachable, /federations/ returns 200")

    # ── Step 2: Create federation ──────────────────────────────────
    step(2, "Create federation")
    FED_ID = "e2e-federation-01"
    code, resp = api("POST", "/federations/", {
        "id": FED_ID, "name": "E2E Test Federation",
        "description": "Full workflow test", "min_clients": 2, "max_rounds": 3
    })
    if code == 409:
        ok("Federation already exists — fetching current state")
        _, resp = api("GET", f"/federations/{FED_ID}")
    fed = resp["data"]
    ok(f"Federation ready", f"id={fed['id']} status={fed['status']}")
    mark_done(f"Federation created: {FED_ID}")

    # ── Step 3: Register clients ───────────────────────────────────
    step(3, "Register 2 clients")
    from trustfl_crypto.keys import ClientIdentity, PublicKeyRegistry
    identities = {}
    for cid in ["e2e-client-01", "e2e-client-02"]:
        identity = ClientIdentity.generate(cid)
        identities[cid] = identity
        code, resp = api("POST", "/clients/", {
            "id": cid, "federation_id": FED_ID,
            "public_key_b64": identity.public_key_b64,
            "capabilities": {"gpu": False, "samples": 100}
        })
        if code == 409:
            ok(f"Client {cid} already registered")
        else:
            client = resp["data"]
            ok(f"Client registered", f"id={client['id']} active={client['is_active']}")
    mark_done("2 clients registered with Ed25519 public keys")

    # ── Step 4: Create training round ─────────────────────────────
    step(4, "Create training round")
    ROUND_NUM = 1
    ROUND_ID = f"{FED_ID}_round{ROUND_NUM}"
    MODEL_VERSION = "v1.0-e2e"
    code, resp = api("POST", "/rounds/", {
        "federation_id": FED_ID,
        "round_number": ROUND_NUM,
        "model_version": MODEL_VERSION
    })
    if code == 409:
        ok(f"Round {ROUND_ID} already exists")
        _, resp = api("GET", f"/rounds/{ROUND_ID}")
    rnd = resp["data"]
    ok(f"Round created", f"id={rnd['id']} status={rnd['status']} model_version={rnd['model_version']}")
    # Advance to ACTIVE
    _, upd = api("PUT", f"/rounds/{ROUND_ID}/status", {"status": "ACTIVE"})
    ok(f"Round activated", f"status={upd['data']['status']}")
    mark_done(f"Round {ROUND_ID} created and set ACTIVE")

    # ── Step 5: Client local training ─────────────────────────────
    step(5, "Client local training (FL core)")
    from trustfl_core.model import TinyLinearModel, generate_synthetic_data
    from trustfl_core.flower_app import FitIns, FitRes

    global_model = TinyLinearModel(in_features=4, seed=42)
    initial_params = global_model.get_parameters()
    ok("Global model created", f"layers={len(initial_params)} weights[0][:3]={initial_params[0][:3]}")

    client_results = {}
    for i, cid in enumerate(["e2e-client-01", "e2e-client-02"]):
        train_data = generate_synthetic_data(100, in_features=4, seed=100+i*10)
        test_data  = generate_synthetic_data(25,  in_features=4, seed=200+i*10)
        local_model = TinyLinearModel(in_features=4)
        local_model.set_parameters(initial_params)

        # Train 3 epochs
        losses = []
        for _ in range(3):
            loss = local_model.train_step(train_data[0], train_data[1], lr=0.05)
            losses.append(loss)
        eval_loss, eval_acc = local_model.evaluate(test_data[0], test_data[1])
        updated_params = local_model.get_parameters()

        client_results[cid] = {
            "params": updated_params,
            "num_examples": 100,
            "train_loss_final": losses[-1],
            "eval_loss": eval_loss,
            "eval_acc": eval_acc
        }
        ok(f"Client {cid} trained",
           f"train_loss={losses[-1]:.4f} eval_loss={eval_loss:.4f} eval_acc={eval_acc:.4f}")
    mark_done("2 clients completed local training on distinct synthetic datasets")

    # ── Step 6: Signed update creation ────────────────────────────
    step(6, "Sign updates (Ed25519 over canonical metadata)")
    from trustfl_crypto.signer import UpdateSigner

    signed_updates = {}
    for cid, res in client_results.items():
        identity = identities[cid]
        signer = UpdateSigner(identity, FED_ID)
        su = signer.sign(
            round_id=ROUND_NUM,
            model_version=MODEL_VERSION,
            parameters=res["params"],
            num_examples=res["num_examples"],
            metrics={"train_loss": res["train_loss_final"], "eval_loss": res["eval_loss"]}
        )
        signed_updates[cid] = su
        ok(f"Update signed for {cid}",
           f"nonce={su.metadata.nonce} artifact_hash={su.metadata.artifact_hash[:20]}...")
    mark_done("Both client updates signed with Ed25519")

    # ── Step 7: Signature verification (coordinator-side) ─────────
    step(7, "Coordinator verifies signatures")
    from trustfl_crypto.verifier import UpdateVerifier, VerificationStatus

    registry = PublicKeyRegistry()
    for cid, identity in identities.items():
        registry.register(cid, identity.public_key_b64)

    verifier = UpdateVerifier(registry)
    verifier.set_round(current_round=ROUND_NUM, accepted_model_versions={MODEL_VERSION})

    for cid, su in signed_updates.items():
        result = verifier.verify(su, expected_client_id=cid)
        if result.status != VerificationStatus.OK:
            fail(f"Signature verification failed for {cid}",
                 f"status={result.status.value} detail={result.detail}",
                 "Signing or verification logic mismatch")
        ok(f"Signature valid for {cid}", result.status.value)
    mark_done("All update signatures verified OK by coordinator")

    # ── Step 8: Artifact storage + hash verification ───────────────
    step(8, "Store update artifacts + verify SHA-256 hashes")
    from trustfl_storage.client import LocalStorageClient

    storage = LocalStorageClient("/tmp/trustfl_e2e_artifacts")
    artifact_metas = {}
    for cid, su in signed_updates.items():
        payload = json.dumps({
            "parameters": su.parameters,
            "num_examples": su.num_examples,
            "client_id": cid,
            "round_id": ROUND_NUM
        }).encode()
        meta = storage.save_artifact(payload, MODEL_VERSION, ROUND_NUM, cid)
        # Immediately re-download and verify
        downloaded = storage.load_artifact(meta.uri, meta.sha256_hash)
        if downloaded != payload:
            fail(f"Artifact round-trip failed for {cid}", "Downloaded bytes differ from uploaded")
        artifact_metas[cid] = meta
        ok(f"Artifact stored+verified for {cid}",
           f"uri={meta.uri} sha256={meta.sha256_hash[:20]}...")
    mark_done("Update artifacts stored to local filesystem and hash-verified")

    # ── Step 9: Submit updates to API ─────────────────────────────
    step(9, "Submit updates to API")
    update_ids = {}
    for i, (cid, su) in enumerate(signed_updates.items()):
        upd_id = f"e2e-upd-{i+1:02d}"
        meta = artifact_metas[cid]
        code, resp = api("POST", "/updates/", {
            "id": upd_id,
            "round_id": ROUND_ID,
            "client_id": cid,
            "artifact_hash": su.metadata.artifact_hash,
            "artifact_id": upd_id + "-art",
            "nonce": su.metadata.nonce,
            "num_examples": su.num_examples,
            "loss": client_results[cid]["eval_loss"]
        })
        if code not in (200, 201, 409):
            fail(f"Update submission for {cid} returned HTTP {code}", str(resp))
        update_ids[cid] = upd_id
        status = resp["data"]["status"] if code != 409 else "ALREADY_EXISTS"
        ok(f"Update submitted for {cid}", f"id={upd_id} status={status}")
    mark_done("Both updates submitted to API with artifact hashes + nonces")

    # ── Step 10: Blockchain — register clients ─────────────────────
    step(10, "Blockchain: register clients")
    from web3 import Web3
    import time as _time

    w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
    if not w3.is_connected():
        fail("Cannot connect to Hardhat RPC at 127.0.0.1:8545",
             "Connection refused", "Hardhat node is not running")

    chain_id = w3.eth.chain_id
    ok(f"RPC connected", f"chain_id={chain_id} block={w3.eth.block_number}")

    with open("packages/contracts/deployments/localhost/contracts.json") as f:
        deploy_data = json.load(f)["contracts"]

    ADMIN_PK = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    admin = w3.eth.account.from_key(ADMIN_PK)

    def send_tx(contract, fn, *args):
        tx = fn(*args).build_transaction({
            "from": admin.address,
            "nonce": w3.eth.get_transaction_count(admin.address),
            "gas": 500000,
            "gasPrice": w3.eth.gas_price,
            "chainId": chain_id
        })
        signed = w3.eth.account.sign_transaction(tx, ADMIN_PK)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status != 1:
            raise RuntimeError(f"Transaction reverted: {tx_hash.hex()}")
        return receipt

    client_reg = w3.eth.contract(
        address=deploy_data["ClientRegistry"]["address"],
        abi=deploy_data["ClientRegistry"]["abi"]
    )

    bc_client_idx = {}
    for i, (cid, identity) in enumerate(identities.items()):
        # On-chain clientId = a deterministic string based on cid
        bc_cid = f"bc-{cid}"
        bc_pubkey = identity.public_key_b64[:64]  # first 64 chars of b64 pubkey (string)
        receipt = send_tx(client_reg, client_reg.functions.registerClient,
                          bc_cid, bc_pubkey)
        bc_client_idx[cid] = bc_cid
        # Record blockchain tx in API
        api("POST", "/blockchain/transactions", {
            "id": f"bc-register-{cid}",
            "tx_hash": receipt.transactionHash.hex(),
            "contract_name": "ClientRegistry",
            "function_name": "registerClient",
            "entity_id": cid,
            "entity_type": "client",
            "status": "CONFIRMED"
        })
        ok(f"Client {cid} registered on-chain", f"tx={receipt.transactionHash.hex()[:20]}...")

    # Verify first client is registered
    first_cid = list(bc_client_idx.values())[0]
    is_registered = client_reg.functions.isClientActive(first_cid).call()
    if not is_registered:
        fail("Client not found on-chain after registration",
             f"isClientActive({first_cid}) returned False")
    ok("On-chain isClientActive() confirmed", f"clientId={first_cid}")
    mark_done("Clients registered on blockchain, tx recorded in API")

    # ── Step 11: Blockchain — create + activate round ──────────────
    step(11, "Blockchain: create and activate round")
    round_reg = w3.eth.contract(
        address=deploy_data["TrainingRoundRegistry"]["address"],
        abi=deploy_data["TrainingRoundRegistry"]["abi"]
    )

    BC_ROUND_ID = 1
    receipt = send_tx(round_reg, round_reg.functions.createRound,
                      BC_ROUND_ID, MODEL_VERSION)
    ok(f"Round created on-chain", f"tx={receipt.transactionHash.hex()[:20]}...")

    receipt = send_tx(round_reg, round_reg.functions.activateRound, BC_ROUND_ID)
    ok(f"Round activated on-chain", f"tx={receipt.transactionHash.hex()[:20]}...")
    api("POST", "/blockchain/transactions", {
        "id": "bc-create-round-1", "tx_hash": receipt.transactionHash.hex(),
        "contract_name": "TrainingRoundRegistry", "function_name": "activateRound",
        "entity_id": ROUND_ID, "entity_type": "round", "status": "CONFIRMED"
    })
    mark_done("Round created and activated on blockchain")

    # ── Step 12: Blockchain — submit updates ───────────────────────
    step(12, "Blockchain: submit update hashes")
    update_reg = w3.eth.contract(
        address=deploy_data["UpdateRegistry"]["address"],
        abi=deploy_data["UpdateRegistry"]["abi"]
    )
    for i, (cid, su) in enumerate(signed_updates.items()):
        bc_upd_id = f"e2e-upd-{i+1:02d}"   # string ID
        bc_cid = bc_client_idx[cid]           # string clientId on-chain
        art_hash_str = su.metadata.artifact_hash  # string (sha256:...)
        nonce_str = su.metadata.nonce             # string nonce
        receipt = send_tx(update_reg, update_reg.functions.submitUpdate,
                          bc_upd_id, BC_ROUND_ID, bc_cid, art_hash_str, nonce_str)
        ok(f"Update {bc_upd_id} submitted on-chain",
           f"tx={receipt.transactionHash.hex()[:20]}...")
    mark_done("Update artifact hashes submitted to blockchain UpdateRegistry")

    # ── Step 13: ZKP — generate commitments ───────────────────────
    step(13, "ZKP: generate Poseidon commitments")
    from trustfl_zkp import compute_poseidon_commitment, build_proof_metadata

    zkp_proofs = {}
    for i, cid in enumerate(identities.keys()):
        priv_commit = secrets.randbelow(10**12) + 1
        pub_commit = compute_poseidon_commitment(
            client_id=i+1, federation_id=1,
            round_id=ROUND_NUM, model_version=1,
            private_commitment=priv_commit
        )
        proof_meta = build_proof_metadata(i+1, 1, ROUND_NUM, 1, pub_commit)
        zkp_proofs[cid] = {"priv": priv_commit, "pub": pub_commit, "meta": proof_meta}
        ok(f"ZKP commitment for {cid}",
           f"public_commitment={pub_commit[:20]}...")
        # Check private witness is NOT in proof_meta
        if str(priv_commit) in str(proof_meta):
            fail(f"Private witness leaked into proof metadata for {cid}",
                 str(proof_meta), "build_proof_metadata must not include private commitment")
        ok(f"Private witness NOT in proof metadata ✓")

        # Submit proof to API
        upd_id = update_ids[cid]
        api("POST", "/proofs/", {
            "id": f"proof-{cid}",
            "update_id": upd_id,
            "client_id": cid,
            "federation_id": FED_ID,
            "round_id": ROUND_ID,
            "model_version": MODEL_VERSION,
            "public_commitment": pub_commit,
            "protocol": "poseidon_commitment_v1"
        })
        ok(f"Proof record stored in API for {cid}")
    mark_done("ZKP commitments generated; proof metadata (public only) stored in API")

    # ── Step 14: ZKP — verify commitments ─────────────────────────
    step(14, "ZKP: verify all commitments")
    from trustfl_zkp import verify_commitment

    for cid, zkp in zkp_proofs.items():
        valid = verify_commitment(
            client_id=list(identities.keys()).index(cid)+1,
            federation_id=1, round_id=ROUND_NUM, model_version=1,
            private_commitment=zkp["priv"],
            public_commitment=zkp["pub"]
        )
        if not valid:
            fail(f"ZKP verification failed for {cid}",
                 f"public_commitment={zkp['pub']}",
                 "Poseidon commitment does not match — prover/verifier mismatch")
        ok(f"ZKP verified for {cid}", "valid=True")

        # Test: wrong private witness must fail
        wrong_valid = verify_commitment(
            client_id=list(identities.keys()).index(cid)+1,
            federation_id=1, round_id=ROUND_NUM, model_version=1,
            private_commitment=zkp["priv"]+999,
            public_commitment=zkp["pub"]
        )
        if wrong_valid:
            fail(f"ZKP accepted wrong witness for {cid}", "", "Security defect in ZKP verifier")
        ok(f"Wrong ZKP witness correctly rejected for {cid}")
    mark_done("All ZKP proofs verified; invalid witnesses rejected")

    # ── Step 15: Aggregation (FedAvg) ─────────────────────────────
    step(15, "Aggregation: weighted FedAvg over client updates")
    # Manual FedAvg: weighted average by num_examples
    all_params = [res["params"] for res in client_results.values()]
    all_n = [res["num_examples"] for res in client_results.values()]
    total_n = sum(all_n)

    aggregated = []
    for layer_idx in range(len(all_params[0])):
        agg_layer = []
        for w_idx in range(len(all_params[0][layer_idx])):
            weighted = sum(
                all_params[c][layer_idx][w_idx] * all_n[c] / total_n
                for c in range(len(all_params))
            )
            agg_layer.append(weighted)
        aggregated.append(agg_layer)

    # Verify aggregated params differ from initial (training happened)
    changed = any(
        abs(aggregated[li][wi] - initial_params[li][wi]) > 1e-8
        for li in range(len(aggregated))
        for wi in range(len(aggregated[li]))
    )
    if not changed:
        fail("Aggregated parameters identical to initial — training had no effect",
             f"initial[0][:3]={initial_params[0][:3]} aggregated[0][:3]={aggregated[0][:3]}")
    ok("FedAvg aggregation complete",
       f"initial[0][:3]={[round(x,5) for x in initial_params[0][:3]]}"
       f" → aggregated[0][:3]={[round(x,5) for x in aggregated[0][:3]]}")
    mark_done("FedAvg weighted aggregation produced new global model parameters")

    # ── Step 16: Store global model artifact + record in API ───────
    step(16, "Store global model artifact + record in API")
    NEW_MODEL_VERSION = "v2.0-e2e"
    global_payload = json.dumps({"parameters": aggregated, "version": NEW_MODEL_VERSION}).encode()
    global_art = storage.save_artifact(global_payload, NEW_MODEL_VERSION, ROUND_NUM, client_id=None)

    # Re-verify
    downloaded = storage.load_artifact(global_art.uri, global_art.sha256_hash)
    if downloaded != global_payload:
        fail("Global model artifact round-trip failed", "Hash mismatch on re-download")
    ok("Global model stored + verified", f"sha256={global_art.sha256_hash[:20]}...")

    code, resp = api("POST", "/artifacts/", {
        "id": "global-model-e2e-r1",
        "federation_id": FED_ID,
        "round_number": ROUND_NUM,
        "uri": global_art.uri,
        "sha256_hash": global_art.sha256_hash,
        "size_bytes": global_art.size,
        "model_version": NEW_MODEL_VERSION
    })
    art_id = resp["data"]["id"] if code in (200, 201) else "global-model-e2e-r1"
    ok("Global model artifact recorded in API", f"id={art_id}")

    # Mark updates as aggregated
    for cid, upd_id in update_ids.items():
        api("PUT", f"/updates/{upd_id}/status", {"status": "AGGREGATED"})
    ok("Updates marked AGGREGATED in API")
    mark_done(f"New global model ({NEW_MODEL_VERSION}) stored, artifact recorded in API")

    # ── Step 17: Round finalization ────────────────────────────────
    step(17, "Finalize round on API and blockchain")
    _, upd = api("PUT", f"/rounds/{ROUND_ID}/status", {
        "status": "FINALIZED",
        "global_model_artifact_id": art_id
    })
    fin_status = upd["data"]["status"]
    if fin_status != "FINALIZED":
        fail(f"Round status after finalization is {fin_status}, expected FINALIZED",
             str(upd["data"]))
    ok("Round FINALIZED in API", f"finalized_at={upd['data'].get('finalized_at')}")

    # Finalize on blockchain
    receipt = send_tx(round_reg, round_reg.functions.finalizeRound, BC_ROUND_ID, NEW_MODEL_VERSION)
    ok("Round finalized on blockchain", f"tx={receipt.transactionHash.hex()[:20]}...")
    api("POST", "/blockchain/transactions", {
        "id": "bc-finalize-round-1",
        "tx_hash": receipt.transactionHash.hex(),
        "contract_name": "TrainingRoundRegistry",
        "function_name": "finalizeRound",
        "entity_id": ROUND_ID, "entity_type": "round", "status": "CONFIRMED"
    })
    mark_done("Round FINALIZED in API; finalizeRound() confirmed on blockchain")

    # ── Step 18: Dashboard data verification ──────────────────────
    step(18, "Dashboard: verify API state is consistent for frontend")
    _, feds = api("GET", "/federations/")
    _, rnd_resp = api("GET", f"/rounds/{ROUND_ID}")
    _, art_resp = api("GET", "/artifacts/")

    final_rnd = rnd_resp["data"]
    final_arts = art_resp["data"]

    checks = {
        "Federation exists": any(f["id"] == FED_ID for f in feds["data"]),
        "Round is FINALIZED": final_rnd["status"] == "FINALIZED",
        "Global model artifact recorded": any(a["id"] == "global-model-e2e-r1" for a in final_arts),
        "Global model version in artifact": any(a["model_version"] == NEW_MODEL_VERSION for a in final_arts),
    }
    for check, result in checks.items():
        if not result:
            fail(f"Dashboard data check failed: {check}",
                 f"API state inconsistent for dashboard rendering")
        ok(f"Dashboard data: {check}")

    # Note dashboard render status
    dash_code = http_get_status(DASHBOARD)
    ok(f"Dashboard HTTP {dash_code}",
       "500 — empty layout.tsx prevents rendering (pre-existing defect, does not affect API data)")
    mark_done("API data verified consistent — dashboard would render correctly if layout.tsx were populated")

    # ── Final Report ───────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("COMPLETE WORKFLOW EXECUTION REPORT")
    print('='*60)
    print("\nAll completed steps:")
    for s in _workflow_steps_done:
        print(f"  {s}")
    print(f"\nFirst Failing Step: None — all 19 steps completed")
    print(f"\nKnown Defect (non-blocker for backend):")
    print(f"  apps/dashboard/app/layout.tsx is empty (0 bytes)")
    print(f"  Effect: Dashboard HTTP 500 on all routes")
    print(f"  Does NOT affect: API, blockchain, ZKP, storage, FL core")
    print(f"\nFINAL VERDICT: NOT READY")
    print(f"  Reason: Dashboard is non-functional (layout.tsx empty)")
    print(f"  All backend steps: READY")
    print('='*60)

if __name__ == "__main__":
    main()
