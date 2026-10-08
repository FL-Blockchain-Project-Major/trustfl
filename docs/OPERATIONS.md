# TrustFL Operations and Command Reference

## Local stack

```bash
cp .env.example .env
docker compose config
docker compose up --build
```

Services and local ports:

| Service | Port | Purpose |
| --- | ---: | --- |
| Dashboard | 3000 | Next.js operations console |
| API | 8000 | FastAPI control plane and OpenAPI |
| Coordinator | 8100 | FL registration, rounds, and signed updates |
| Hardhat | 8545 | Development EVM node only |
| IPFS API | 5001 | Artifact storage API |
| PostgreSQL | 5432 | Control-plane metadata |

The Compose stack is a development/integration environment. It uses a local
Hardhat chain, development credentials, a single coordinator, and local
persistence volumes. Do not expose it to the public internet.

## Checks

```bash
ruff check .
pytest tests/
make check
make lint
cd apps/dashboard && npm test && npm run build
cd packages/contracts && npm test && npm run compile
docker compose config
docker compose build
```

## Production readiness boundary

Production-ready foundations include signed update enforcement, canonical
artifact hashes, PostgreSQL migrations, request-size/rate-limit middleware,
role-scoped API keys, storage integrity checks, contract audit records, and
the read-only dashboard.

The following remain deployment responsibilities or deferred capabilities:

- Use an external secret manager/KMS/HSM for coordinator keys and API keys.
- Terminate TLS at a reverse proxy or managed ingress.
- Use HA PostgreSQL, backups, monitoring, and tested recovery procedures.
- Use a managed/pinned IPFS service or an approved object-storage adapter.
- Deploy contracts to a reviewed network and manage ABI/address configuration.
- Add a durable blockchain outbox/reconciliation worker before claiming
  database/chain atomicity.
- Integrate and enforce ZKP verification if proof-backed updates are required.
- Add an identity provider if operator identity, token rotation, tenant
  isolation, and per-user audit attribution are required.

## Troubleshooting

- If the dashboard shows `Dashboard API is unavailable`, verify API health at
  `/health/`, `INTERNAL_API_URL`, and the server-side read key.
- If blockchain rows are empty, check that the coordinator can reach Hardhat or
  the configured RPC and that its transaction audit callback can reach the API.
- If updates are rejected, inspect coordinator logs for signature, round,
  nonce, model-version, or artifact-hash validation failures.
- If Compose cannot bind port 8100, stop the unrelated process or change the
  host-side port mapping; do not weaken coordinator request handling.
