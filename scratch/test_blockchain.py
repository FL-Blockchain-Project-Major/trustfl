import json
import os
import sys
from web3 import Web3

# Hardhat default accounts
ADMIN_PK = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
USER_PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"

w3 = Web3(Web3.HTTPProvider("http://localhost:8545"))
if not w3.is_connected():
    print("Failed to connect to RPC")
    sys.exit(1)

print(f"Connected to RPC. Chain ID: {w3.eth.chain_id}")

with open("/home/sayam/Desktop/TrustFL/packages/contracts/deployments/localhost/contracts.json") as f:
    deployments = json.load(f)

admin_acct = w3.eth.account.from_key(ADMIN_PK)
user_acct = w3.eth.account.from_key(USER_PK)

print(f"Admin address: {admin_acct.address}")
print(f"User address: {user_acct.address}")

def get_contract(name):
    data = deployments[name]
    print(f"Contract {name}: {data['address']}")
    return w3.eth.contract(address=data["address"], abi=data["abi"])

client_reg = get_contract("ClientRegistry")
round_reg = get_contract("TrainingRoundRegistry")
update_reg = get_contract("UpdateRegistry")

def send_tx(contract, function_name, acct, *args):
    func = getattr(contract.functions, function_name)
    try:
        tx = func(*args).build_transaction({
            'from': acct.address,
            'nonce': w3.eth.get_transaction_count(acct.address),
            'gasPrice': w3.eth.gas_price
        })
        signed = w3.eth.account.sign_transaction(tx, acct.key)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status == 1:
            return True, receipt.transactionHash.hex(), None
        else:
            return False, receipt.transactionHash.hex(), "Transaction reverted (status 0)"
    except Exception as e:
        return False, None, str(e)

passed = []
failed = []

def test(name, contract, func, acct, args, expect_success=True):
    success, tx_hash, err = send_tx(contract, func, acct, *args)
    if success == expect_success:
        passed.append(f"{name} (Tx/Result: {tx_hash if tx_hash else err})")
        print(f"PASS: {name}")
    else:
        failed.append(f"{name} - Expected {expect_success}, got {success}. Err: {err}")
        print(f"FAIL: {name}")

print("\n--- Running Tests ---")

# 1. Client Registration
test("Register Client (Admin)", client_reg, "registerClient", admin_acct, ("client1", "pubkey1"))
test("Register Client (Unauthorized)", client_reg, "registerClient", user_acct, ("client2", "pubkey2"), expect_success=False)

# 2. Round Creation
test("Create Round (Admin)", round_reg, "createRound", admin_acct, (1, "v1.0"))
test("Activate Round (Admin)", round_reg, "activateRound", admin_acct, (1,))
test("Invalid State Transition (Re-create Round)", round_reg, "createRound", admin_acct, (1, "v1.1"), expect_success=False)

# 3. Update Submission
test("Submit Update (Admin)", update_reg, "submitUpdate", admin_acct, ("upd1", 1, "client1", "hash1", "nonce1"))
test("Duplicate Update ID (Admin)", update_reg, "submitUpdate", admin_acct, ("upd1", 1, "client1", "hash2", "nonce2"), expect_success=False)
test("Replay Nonce (Admin)", update_reg, "submitUpdate", admin_acct, ("upd2", 1, "client1", "hash3", "nonce1"), expect_success=False)
test("Submit to Invalid Round (Admin)", update_reg, "submitUpdate", admin_acct, ("upd3", 999, "client1", "hash4", "nonce3"), expect_success=False)

# 4. Verification and Aggregation
test("Verify Update (Admin)", update_reg, "markVerificationState", admin_acct, ("upd1", True))
test("Aggregate Update (Admin)", update_reg, "recordAggregation", admin_acct, ("upd1",))
test("Finalize Round (Admin)", round_reg, "finalizeRound", admin_acct, (1, "v2.0"))

print("\n=== BLOCKCHAIN VERDICT ===")
print(f"Passed Transactions: {len(passed)}")
for p in passed: print(f" - {p}")
print(f"Failed Transactions: {len(failed)}")
for f in failed: print(f" - {f}")

if len(failed) == 0:
    print("\nFINAL VERDICT: READY FOR NEXT STAGE")
else:
    print("\nFINAL VERDICT: DO NOT PROCEED")
