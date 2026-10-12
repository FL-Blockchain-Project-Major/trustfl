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

## 4. TLS Configuration

### Coordinator TLS (direct termination)

Set two environment variables on the coordinator to enable TLS directly without a reverse proxy:

```bash
COORDINATOR_TLS_CERT=/path/to/server.crt   # PEM certificate (chain if needed)
COORDINATOR_TLS_KEY=/path/to/server.key    # PEM private key
```

The coordinator reads these at startup and passes them to the ASGI server (`uvicorn`).
If either variable is unset, the coordinator starts in plain HTTP mode — acceptable for
loopback/dev, but **disallowed in production** (see below).

### Client CA bundle

Clients verify the coordinator's TLS certificate against a CA bundle.  Set **one** of:

```bash
FL_CA_BUNDLE=/path/to/ca-bundle.crt           # preferred
COORDINATOR_CA_BUNDLE=/path/to/ca-bundle.crt  # legacy alias
```

If neither is set, the system default CA store is used (`ssl.create_default_context()`).
Pass `--ca-bundle /path/to/ca-bundle.crt` to the client CLI for the same effect.

### Reverse proxy / TLS termination (recommended for production)

Terminating TLS at an NGINX or ALB layer avoids distributing the private key to
application containers.  Example NGINX snippet:

```nginx
server {
    listen 443 ssl;
    server_name coordinator.example.com;

    ssl_certificate     /etc/ssl/server.crt;
    ssl_certificate_key /etc/ssl/server.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://coordinator:8100;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Point clients at `https://coordinator.example.com`.
The coordinator itself can run plain HTTP on the internal network (`http://coordinator:8100`).

### Production HTTP refusal

When `ENVIRONMENT=production` the client agent rejects any non-loopback `http://`
coordinator URL at startup:

```
ValueError: Production environment requires HTTPS for non-loopback coordinator URL.
```

This check is in `apps/client/network/agent.py::_is_loopback()`.  Loopback addresses
(`127.x`, `::1`, `localhost`) are exempt to allow integration tests.

## 5. Artifact Size Limit

The coordinator enforces a hard **1 MB per-request body limit**
(`MAX_BODY_BYTES = 1_048_576` in `apps/coordinator/network/server.py`).

Real YOLO neural-network weights (e.g., YOLOv8n `.pt` files) are typically 6–40 MB and
**cannot** be submitted through the current JSON artifact channel.  The coordinator will
return a `413 Request Entity Too Large` error.

**Current state:** The bundled `SimulatedDetector` (see §6) uses ≈ 57 floats and fits
well within this limit.  Chunked or binary artifact upload is a planned future
enhancement; it is **not implemented**.  Do not deploy real YOLO weights until this
limit is raised or chunked upload is available.

## 6. Model Disclaimer — SimulatedDetector

The class formerly named `YOLOModelWrapper` has been renamed `SimulatedDetector`
(backwards-compatible alias `YOLOModelWrapper` is retained).

**`SimulatedDetector` is NOT a real object-detection model.** It:

- Uses 57 floats (three parameter layers: 40-float detection heads, 16-float backbone, 1 bias).
- Simulates training with a gradient-step approximation on VisDrone bounding boxes.
- Reports `accuracy_proxy`, `precision`, and `recall` as formula-derived scalars — **NOT mAP50 or mAP50-95**.
- The `HAVE_ULTRALYTICS` flag is set only if the `ultralytics` package can actually be imported.

The class is suitable for end-to-end pipeline testing and federated-learning protocol
validation.  It is **not suitable** for benchmarking real detection accuracy or for any
production model-quality claim.  Replace it with a real Ultralytics-backed implementation
(which will also require the chunked artifact upload mentioned in §5) when genuine YOLO
evaluation is needed.

