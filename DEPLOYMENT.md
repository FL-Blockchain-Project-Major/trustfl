# TrustFL Deployment Guide

## 1. Development (Local)
The easiest way to spin up the entire TrustFL stack locally is using `docker compose`. This creates the Postgres DB, IPFS development node, local Hardhat blockchain, API, Coordinator, Dashboard, and two simulated Clients. These defaults are for development only.

```bash
cp .env.example .env
docker-compose up --build
```
- The Compose startup waits for Hardhat, compiles and deploys contracts dynamically,
  and shares the generated deployment JSON with the coordinator. No transient
  contract address is hardcoded.
- Dashboard: http://localhost:3000
- API Docs: http://localhost:8000/docs
- IPFS UI: http://localhost:5001/webui

## 2. Staging
Staging deployments should mirror production closely but can use cheaper, managed services.
- **Database**: Managed PostgreSQL.
- **Blockchain**: A testnet like Sepolia or a dedicated staging roll-up.
- **IPFS**: Pinata or Infura IPFS endpoint.
- **Compute**: A managed container platform or Kubernetes deployment.
- **Secrets**: Use a platform secret store for CI and runtime injection. Do NOT commit `.env`.

## 3. Production
Production requires strict isolation, redundancy, explicit CORS origins, and KMS for coordinator signing keys. The repository's Compose stack is not a production HA deployment.

For production API requests, send `Authorization: Bearer $API_SECRET_KEY`. The coordinator
also requires Ed25519 client public keys at registration and rejects unsigned or invalid
update submissions. Set `COORDINATOR_REQUIRE_SIGNATURES=true` explicitly when deploying
the coordinator outside the development Compose stack.
- **Coordinator & API**: Deploy behind an Application Load Balancer (ALB) or NGINX with TLS termination. Ensure minimum 2 instances of API. Coordinator must be a singleton per federation to prevent race conditions.
- **Smart Contracts**: Deploy to Ethereum Mainnet or an L2 (Arbitrum/Optimism). Store the generated contract ABI/address JSON in the environment configuration.
- **ZKP**: The package is independently tested and optional in the coordinator path;
  do not document it as mandatory until a verifier is explicitly enabled.
- **Private Key**: Inject the Coordinator's private key via an HSM/KMS (e.g. AWS KMS). Never pass it as an unencrypted environment variable.
- **Storage**: Use a decentralized storage provider network (Filecoin/Arweave) or enterprise-grade IPFS pinning service.
