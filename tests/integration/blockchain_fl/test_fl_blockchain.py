import os
import socket
import sys
import time

import requests

# Ensure paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
from trustfl_crypto.keys import ClientIdentity
from trustfl_crypto.signer import UpdateSigner

from apps.coordinator.network.server import CoordinatorServer
from packages.blockchain.trustfl_blockchain.client import BlockchainClient


def _get_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

def run_test():
    contracts_path = "packages/contracts/deployments/localhost/contracts.json"
    # standard hardhat dev key
    pk = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

    print("--- [1] Init Blockchain Client ---")
    bc_client = BlockchainClient(
        rpc_url="http://127.0.0.1:8545",
        contracts_json_path=contracts_path,
        private_key=pk,
        network_name="localhost"
    )

    port = _get_port()
    print(f"--- [2] Init Coordinator on port {port} ---")
    server = CoordinatorServer(
        host="127.0.0.1",
        port=port,
        min_clients=1,
        num_rounds=1,
        round_timeout_seconds=30.0,
        blockchain_client=bc_client
    )
    server.start()
    time.sleep(1) # wait for server to bind

    print("--- [3] Init Client Agent ---")
    import uuid
    client_test_id = f"client_{uuid.uuid4().hex[:6]}"
    identity = ClientIdentity.generate(client_test_id)
    cid = identity.client_id

    print("--- [4] Client Register ---")
    resp = requests.post(f"http://127.0.0.1:{port}/register", json={
        "client_id": cid,
        "capabilities": {"pubkey": identity.public_key_b64}
    })
    ok = resp.status_code == 200 and resp.json().get("accepted")
    print(f"Client registered: {ok}")
    assert ok, "Client failed to register"

    # Check blockchain
    print("Checking client active on blockchain...")
    active = bc_client.client_registry.functions.isClientActive(cid).call()
    print(f"Blockchain isClientActive: {active}")
    assert active, "Client not active on blockchain"

    print("--- [5] Wait for Round Instructions ---")
    instr = None
    for _ in range(20):
        resp = requests.get(f"http://127.0.0.1:{port}/round/instructions/{cid}")
        if resp.status_code == 200:
            instr = resp.json()
            if instr.get("is_active"):
                break
        time.sleep(0.5)

    assert instr and instr["is_active"], "Round did not become active"
    round_id = instr["round_id"]
    print(f"Round {round_id} is active")

    # Check blockchain round
    round_active = bc_client.round_registry.functions.isRoundActive(round_id).call()
    print(f"Blockchain isRoundActive: {round_active}")
    assert round_active, "Round not active on blockchain"

    print("--- [6] Client Sign and Submit Update ---")
    signer = UpdateSigner(identity, "test_federation")
    signed_update = signer.sign(
        round_id=round_id,
        parameters=[[0.1, 0.2], [0.3, 0.4]],
        num_examples=100,
        metrics={"loss": 0.5},
        model_version="test_model_v1"
    )

    # Submit update to coordinator
    req_body = signed_update.to_dict()
    req_body["client_id"] = cid
    req_body["round_id"] = round_id

    resp = requests.post(
        f"http://127.0.0.1:{port}/submit",
        json=req_body
    )
    print(f"Submit response: {resp.status_code} {resp.text}")
    assert resp.status_code == 200, "Update submission failed"

    print("--- [7] Wait for Round Finalization ---")
    server.state.wait_until_done(timeout=10)
    server.stop()

    # Check if update is verified and aggregated
    update_id = f"update_{cid}_{round_id}"
    update_info = bc_client.update_registry.functions.getUpdate(update_id).call()
    # Enum UpdateStatus { None, Submitted, Verified, Aggregated, Rejected } => 3 is Aggregated
    print(f"Blockchain Update Status (3=Aggregated): {update_info[4]}")
    assert update_info[4] == 3, "Update was not aggregated on chain"

    print("--- [8] SUCCESS ---")

if __name__ == "__main__":
    run_test()
