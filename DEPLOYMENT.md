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
- IPFS API is intentionally not published to the host. For development diagnostics use
  `docker compose exec ipfs ipfs id` (or the loopback-only gateway at http://localhost:8081).

## 2. Staging
Staging deployments should mirror production closely but can use cheaper, managed services.
- **Database**: Managed PostgreSQL.
- **Blockchain**: A testnet like Sepolia or a dedicated staging roll-up.
- **IPFS**: Pinata or Infura IPFS endpoint.
- **Compute**: A managed container platform or Kubernetes deployment.
- **Secrets**: Use a platform secret store for CI and runtime injection. Do NOT commit `.env`.

## 3. Production
Production requires strict isolation, redundancy, explicit CORS origins, and KMS for coordinator signing keys. The repository's Compose stack is not a production HA deployment.

Production API access uses separate role-scoped credentials: configure
`API_READ_KEY`, `API_WRITE_KEY`, and `API_ADMIN_KEY`; use the read key for GET/HEAD,
the write key for mutations, and the admin key for DELETE operations. The coordinator
also requires Ed25519 client public keys at registration and rejects unsigned or invalid
update submissions. Set `COORDINATOR_REQUIRE_SIGNATURES=true` explicitly when deploying
the coordinator outside the development Compose stack.
- **Coordinator & API**: Deploy behind an Application Load Balancer (ALB) or NGINX with TLS termination. Ensure minimum 2 instances of API. Coordinator must be a singleton per federation to prevent race conditions.
- **Ingress headers**: Redirect HTTP to HTTPS and enable HSTS at the TLS ingress after validating the domain and certificate. Do not enable HSTS on plaintext development Compose endpoints.
- **Enrollment**: Provision each client ID and its Ed25519 public key in
  `COORDINATOR_ENROLLMENT_ALLOWLIST`. Registration includes a signed
  proof-of-possession; every subsequent coordinator request is separately
  signed and replay-protected. To rotate or revoke a key, update/remove that
  client’s allow-list entry and restart the singleton coordinator. Do not set
  `COORDINATOR_INSECURE_DEV_AUTH=true` outside disposable development.
- **Smart Contracts**: Deploy to Ethereum Mainnet or an L2 (Arbitrum/Optimism). Store the generated contract ABI/address JSON in the environment configuration.
- **ZKP**: The package is independently tested and optional in the coordinator path;
  do not document it as mandatory until a verifier is explicitly enabled.
- **Private Key**: Inject the Coordinator's private key via an HSM/KMS (e.g. AWS KMS). Never pass it as an unencrypted environment variable.
- **Storage**: Use a decentralized storage provider network (Filecoin/Arweave) or enterprise-grade IPFS pinning service.
