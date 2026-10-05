# TrustFL Deployment Guide

## 1. Development (Local)
The easiest way to spin up the entire TrustFL stack locally is using `docker-compose`. This creates the Postgres DB, IPFS development node, local Hardhat blockchain, API, Coordinator, Dashboard, and two simulated Clients.

```bash
cp .env.example .env
docker-compose up --build
```
- Dashboard: http://localhost:3000
- API Docs: http://localhost:8000/docs
- IPFS UI: http://localhost:5001/webui

## 2. Staging
Staging deployments should mirror production closely but can use cheaper, managed services.
- **Database**: Managed PostgreSQL (e.g., AWS RDS or GCP Cloud SQL).
- **Blockchain**: A testnet like Sepolia or a dedicated staging roll-up.
- **IPFS**: Pinata or Infura IPFS endpoint.
- **Compute**: ECS, GKE, or Docker Swarm. Use `docker-compose.staging.yml` if using Swarm.
- **Secrets**: Use AWS Secrets Manager or GitHub Actions Secrets for CI deployments. Do NOT commit `.env`.

## 3. Production
Production requires strict isolation, redundancy, and KMS for coordinator signing keys.
- **Coordinator & API**: Deploy behind an Application Load Balancer (ALB) or NGINX with TLS termination. Ensure minimum 2 instances of API. Coordinator must be a singleton per federation to prevent race conditions.
- **Smart Contracts**: Deploy to Ethereum Mainnet or an L2 (Arbitrum/Optimism). Store the contract ABIs and addresses in the environment configuration.
- **Private Key**: Inject the Coordinator's private key via an HSM/KMS (e.g. AWS KMS). Never pass it as an unencrypted environment variable.
- **Storage**: Use a decentralized storage provider network (Filecoin/Arweave) or enterprise-grade IPFS pinning service.
