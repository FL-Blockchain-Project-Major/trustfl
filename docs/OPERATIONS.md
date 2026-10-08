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
| IPFS gateway | 8081 | Loopback-only artifact gateway (the API remains container-internal) |
| PostgreSQL | 5432 | Control-plane metadata |

The Compose stack is a development/integration environment. It uses a local
Hardhat chain, development credentials, a single coordinator, and local
persistence volumes. Published ports are loopback-only; IPFS's API is container-internal.
Do not expose it to the public internet. Production TLS ingress must enforce HTTPS and HSTS.
For safe IPFS diagnostics, run `docker compose exec ipfs ipfs id`; do not publish port 5001.

`FL_MAX_CLIENT_WEIGHT_SHARE` (default `0.5`) clips a client’s effective FedAvg
weight only after all updates are collected. This makes the defense independent
of submission order; `FL_MAX_NUM_EXAMPLES_PER_UPDATE` remains the hard input cap.

If chain finalization fails, the coordinator retries with exponential backoff,
bounded by `FL_FINALIZE_MAX_RETRIES`. A terminal `finalization.terminal_error`
in authenticated coordinator status means the round is frozen without re-aggregation.
Investigate the chain transaction/state, repair the chain connection or state, then
restart the coordinator only after confirming the round can be finalized.

The generated Ethers declarations in `packages/contracts/types/ethers-contracts`
are intentionally tracked so downstream consumers can use the deployed ABI without
running Hardhat. Contract CI compiles first and fails if generation changes them.
Each on-chain round preserves `inputModelVersion` (the model clients trained from)
and `outputModelVersion` (the finalized aggregate); do not treat the latter as a
replacement for input provenance.

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
  host-side port mapping with `COORDINATOR_HOST_PORT=18100`; clients continue
  to use the internal `coordinator:8100` address.
- Compose uses `FL_FEDERATION_ID=fed-default` for the coordinator, clients,
  PostgreSQL records, API queries, and dashboard. Set the same value for every
  service when running another federation.
# Operations security notes

The coordinator requires Ed25519 signatures by default. In a deployed stack set
`COORDINATOR_ENROLLMENT_TOKEN` to a high-entropy secret; clients send it as a
Bearer credential for registration, heartbeats, and update submission. A token
is deliberately optional only in explicit `ENVIRONMENT=development` to keep the
local in-process examples usable.

Set `API_AUTH_REQUIRED=true` with distinct `API_READ_KEY`, `API_WRITE_KEY`, and
`API_ADMIN_KEY`. The dashboard server proxy uses the read key internally and
only exposes read-only API prefixes. Set `DASHBOARD_ACCESS_KEY` to protect that
proxy when it is published.

`FL_MAX_NUM_EXAMPLES_PER_UPDATE` (default 1,000,000) caps client-reported
sample counts before FedAvg, limiting a single client’s influence. A round with
fewer than `FL_MIN_CLIENTS` accepted updates is recorded as `FAILED`, never
finalized. Persist client private keys on the per-client Compose volumes; key
rotation must be an authenticated re-registration and should retain an
old-key signature audit trail.

ZKP artifacts are standalone and are not used as coordinator admission proofs.
Do not treat a stored proof’s validity field as verification; only a dedicated
verifier may set it.
