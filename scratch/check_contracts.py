import json

from web3 import Web3

w3 = Web3(Web3.HTTPProvider("http://localhost:8545"))
with open("/home/sayam/Desktop/TrustFL/packages/contracts/deployments/localhost/contracts.json") as f:
    deployments = json.load(f)

print("Chain ID:", w3.eth.chain_id)
for name, data in deployments.items():
    code = w3.eth.get_code(data["address"])
    print(f"{name} ({data['address']}): {'Deployed' if len(code) > 2 else 'Not Deployed'}")
