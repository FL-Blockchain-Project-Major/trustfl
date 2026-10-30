# TrustFL Scenario 3: Different Devices, Different Networks (WAN) End-to-End Execution Guide
## Cloud Coordinator + 3 NAT-Isolated Edge Sites on Real VisDrone Data

This document is a reproducible walkthrough of **Scenario 3 (Scenario C in `docs/DEPLOYMENT_SCENARIOS.md`)**:
- **Topology**: one cloud host (Coordinator, FastAPI gateway, Next.js dashboard, PostgreSQL, IPFS Kubo, EVM chain, NGINX TLS proxy) and **three edge sites on three different networks**, each behind its own NAT router with no inbound ports.
- **Workload**: real drone imagery and bounding boxes from **VisDrone2019-DET-val** (548 images, 38,759 boxes), split into one private partition per site.
- **Run executed**: 3 edge sites, **10 federated rounds**, production mode, signed requests, enrollment allow-list, TLS, IPFS artifact storage, on-chain audit.

> **How this was tested (read this first).** The walkthrough was executed in a Linux sandbox that has no real second network. The "internet" is emulated with Linux network namespaces: the cloud host and each edge site sit in separate namespaces, each edge site is behind its own NAT router (`MASQUERADE`), and the cloud host is reachable only through a router that forwards **ports 80 and 443** (nothing else). Outputs below are real captured output from that run. What this does **not** reproduce: real internet latency, packet loss, ISP/CGNAT behaviour, Let's Encrypt, a public DNS name, Pinata, Tailscale, and Docker Compose (Docker Hub was unreachable from the sandbox). Section 9 lists what remains untested.

---

## Table of Contents
1. [Architecture & Traffic Flow](#1-architecture--traffic-flow)
2. [Prerequisites](#2-prerequisites)
3. [Step 1 – Cloud Host: Infrastructure Services](#3-step-1--cloud-host-infrastructure-services)
4. [Step 2 – TLS: Private CA, Certificate, NGINX Reverse Proxy](#4-step-2--tls-private-ca-certificate-nginx-reverse-proxy)
5. [Step 3 – Dataset Partitions & Edge Identities](#5-step-3--dataset-partitions--edge-identities)
6. [Step 4 – Start the Cloud Control Plane](#6-step-4--start-the-cloud-control-plane)
7. [Step 5 – Verify the Network Path From an Edge Site](#7-step-5--verify-the-network-path-from-an-edge-site)
8. [Step 6 – Start the Edge Clients & Observe the Federation](#8-step-6--start-the-edge-clients--observe-the-federation)
9. [Verification & Live Evidence](#9-verification--live-evidence)
10. [Failure & Security Tests Over the WAN Path](#10-failure--security-tests-over-the-wan-path)
11. [Issues Found While Testing (Read Before Production)](#11-issues-found-while-testing-read-before-production)
12. [What Was Not Tested](#12-what-was-not-tested)
13. [Troubleshooting](#13-troubleshooting)
14. [Teardown](#14-teardown)

---

## 1. Architecture & Traffic Flow

```
   EDGE SITES (each behind its own NAT, no inbound ports)              CLOUD HOST (public 198.51.100.1)
 ┌─────────────────────────────────┐
 │ Hospital A  cli_hospital_a      │  NAT 198.51.100.10
 │ 192.168.100.2 (private)         ├──────────┐
 └─────────────────────────────────┘          │         ┌─────────────────────────────────────────────┐
 ┌─────────────────────────────────┐          │  :443   │ NGINX (TLS 1.2/1.3, HSTS, 1 MB body cap,    │
 │ Hospital B  cli_hospital_b      │  NAT .11 ├────────►│ 120 req/min/IP rate limit)                  │
 │ 192.168.101.2 (private)         ├──────────┤  HTTPS  └──────────────────┬──────────────────────────┘
 └─────────────────────────────────┘          │                            │ HTTP 127.0.0.1:8100
 ┌─────────────────────────────────┐          │         ┌──────────────────▼──────────────────────────┐
 │ Factory C   cli_factory_c       │  NAT .12 │         │ Coordinator (allow-list + Ed25519 verify)   │
 │ 192.168.102.2 (private)         ├──────────┘         └───┬───────────┬─────────────┬───────────────┘
 └─────────────────────────────────┘                        │           │             │
                                                      PostgreSQL     IPFS Kubo     EVM chain
                                                      127.0.0.1      127.0.0.1     127.0.0.1:8545
   Also on the cloud host, loopback only: FastAPI :8000, Dashboard :3000
```

### Network invariants verified in this run
1. **Edge sites only make outbound HTTPS requests.** The coordinator never connects to an edge site. In the run, the only source addresses in the NGINX access log were the three NAT addresses.
2. **Only 443 (and a 301 on 80) is exposed.** Coordinator `:8100`, API `:8000`, dashboard `:3000`, Postgres, IPFS and the chain all listen on `127.0.0.1` and were unreachable from the edge networks (Section 7).
3. **Production mode refuses plain HTTP** to a non-loopback coordinator (Section 10).
4. **Every request is signed** (Ed25519) with a timestamp and one-time nonce; unsigned requests get `401`.

### Lifecycle
1. Each site generates its own Ed25519 key locally; only the **public key** is sent to the coordinator operator.
2. The coordinator operator puts all public keys in `COORDINATOR_ENROLLMENT_ALLOWLIST`.
3. Each client registers with a signed proof; the coordinator checks it against the allow-list and registers the client on-chain.
4. With `FL_MIN_CLIENTS=3` registered, round 1 starts. Each client trains locally, signs the update, and POSTs it. The coordinator verifies signature, artifact hash, round and model version, stores the update in IPFS, records `submitUpdate` / `markVerificationState` on-chain, runs FedAvg, pins the global model to IPFS, records `recordAggregation`, and `finalizeRound`.
5. After the last round the coordinator reports `DONE`, waits a 15 s shutdown grace period, and exits `0`. Clients see `Federation DONE` and exit `0`.

---

## 2. Prerequisites

| Item | Cloud host | Each edge site |
| :--- | :--- | :--- |
| OS | Linux (Ubuntu 24.04 used) | Linux/macOS with Python |
| Python | 3.11 or 3.12 (**see note**) | same |
| Node | 22.x (contracts, dashboard) | – |
| Services | PostgreSQL 15+, IPFS Kubo v0.32.1, NGINX | – |
| Network | inbound 80/443 | outbound 443 only |
| Clock | NTP-synchronised | NTP-synchronised |

> **Python version note.** `requirements.txt` pins `Pillow==10.3.0`, which has no wheel for Python 3.13 and fails to build. Use Python 3.11 or 3.12 (`python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt` worked).

Clone and install on the cloud host and on every edge site:
```bash
git clone https://github.com/FL-Blockchain-Project-Major/trustfl && cd trustfl
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
Cloud host only:
```bash
(cd packages/contracts && npm ci && npx hardhat compile)
(cd apps/dashboard && npm ci && npm run build)
```

---

## 3. Step 1 – Cloud Host: Infrastructure Services

Run these on the cloud host. (In the sandbox they ran inside the cloud namespace; on a real host just run them normally, ideally under systemd.)

### 3.1 PostgreSQL
```bash
# create the production database and user (example)
sudo -u postgres psql -c "CREATE USER trustfl_admin WITH PASSWORD 'StrongPass';"
sudo -u postgres psql -c "CREATE DATABASE trustfl_prod OWNER trustfl_admin ENCODING 'UTF8';"
```
> The database **must be UTF-8**. A cluster created with `SQL_ASCII` made SQLAlchemy fail at startup with `TypeError: cannot use a string pattern on a bytes-like object`.

### 3.2 IPFS (Kubo v0.32.1 — same version as `docker-compose.yml`)
```bash
ipfs init --profile server
ipfs daemon &
curl -s -X POST http://127.0.0.1:5001/api/v0/id | head -c 80
```
**Output:**
```
{"ID":"12D3KooWJSbV86WuDsrD1Lz...
```
Keep the IPFS API (`5001`) bound to loopback. It has no authentication.

### 3.3 EVM chain and contracts
```bash
cd packages/contracts
npx hardhat node --hostname 127.0.0.1 &
HARDHAT_RPC_URL=http://127.0.0.1:8545 npx hardhat run scripts/deploy.js --network localhost
```
**Output:**
```
ClientRegistry deployed to: 0x5FbDB2315678afecb367f032d93F642f64180aa3
TrainingRoundRegistry deployed to: 0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512
UpdateRegistry deployed to: 0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0
Granted COORDINATOR_ROLE to deployer

Deployment artifacts saved to: deployments/localhost/contracts.json
```
> `hardhat node` is a development chain with publicly known keys (the `COORDINATOR_PRIVATE_KEY` used below is Hardhat's well-known account #0). For a real deployment use a real network, a funded key from a KMS, and a different `BLOCKCHAIN_RPC_URL`.

---

## 4. Step 2 – TLS: Private CA, Certificate, NGINX Reverse Proxy

This run used a **private CA** (as in the LAN section of the deployment guide) because Let's Encrypt cannot be used in a sandbox. With a public domain, use Certbot instead and skip `FL_CA_BUNDLE` on clients.

### 4.1 Create the CA and a server certificate whose SAN matches the DNS name clients use
```bash
mkdir -p /etc/trustfl/certs && cd /etc/trustfl/certs

openssl req -x509 -new -nodes -newkey rsa:2048 -keyout ca.key -sha256 -days 365 -out ca.crt \
    -subj "/C=US/ST=Security/O=TrustFL CA/CN=TrustFL-Root-CA"

cat > san.cnf <<'EOF'
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
O = TrustFL
CN = coordinator.trustfl.test

[v3_req]
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = coordinator.trustfl.test
EOF

openssl req -new -newkey rsa:2048 -nodes -keyout server.key -out server.csr -config san.cnf
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out server.crt -days 365 -sha256 -extfile san.cnf -extensions v3_req
cat server.crt ca.crt > fullchain.pem
chmod 600 server.key ca.key
openssl verify -CAfile ca.crt server.crt
```
**Output:**
```
server.crt: OK
```
Copy **only `ca.crt`** (never `ca.key` or `server.key`) to each edge site, e.g. `/etc/trustfl/certs/ca.crt`.

In the sandbox the name was resolved with `echo "198.51.100.1 coordinator.trustfl.test" >> /etc/hosts` on each edge. In production use a real DNS `A` record.

### 4.2 NGINX configuration
This is the configuration from the deployment guide (`/etc/nginx/sites-available/trustfl.conf`, inside the `http {}` context) with the sandbox's certificate paths:
```nginx
limit_req_zone $binary_remote_addr zone=trustfl_limit:10m rate=120r/m;

server {
    listen 80;
    server_name coordinator.trustfl.test;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name coordinator.trustfl.test;

    ssl_certificate     /etc/trustfl/certs/fullchain.pem;
    ssl_certificate_key /etc/trustfl/certs/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;

    client_max_body_size 1M;

    location / {
        limit_req zone=trustfl_limit burst=20 nodelay;
        proxy_pass http://127.0.0.1:8100;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 90s;
        proxy_connect_timeout 10s;
    }
}
```
```bash
sudo nginx -t && sudo systemctl reload nginx
```
**Output:**
```
nginx: the configuration file ... syntax is ok
nginx: configuration file ... test is successful
```
> NGINX 1.24 (Ubuntu 24.04) accepts `listen 443 ssl http2;`. On NGINX ≥ 1.25.1 that form is deprecated and you should write `listen 443 ssl;` plus `http2 on;`.

Firewall on the cloud host: allow **only** `80/tcp` and `443/tcp` from the internet. Do **not** open 8100, 8000, 3000, 5432, 5001 or 8545.

---

## 5. Step 3 – Dataset Partitions & Edge Identities

### 5.1 Give each site its own private partition
In a real deployment each site already owns its data. To simulate that with VisDrone, split the validation set into three non-overlapping partitions and place **one** on each site:
```bash
PYTHONPATH=packages/ml_core python datasets/tools/visdrone_prep/prepare.py \
  --images  datasets/raw/VisDrone2019-DET-val/images \
  --annotations datasets/raw/VisDrone2019-DET-val/annotations \
  --output  /tmp/partitions --clients 3 --samples-per-client 150 --seed 11
```
**Output:**
```
==> Validating source dataset ...
Source verified: 548 valid image-annotation pairs (38759 bounding boxes).
Dataset partitions prepared for 3 clients in /tmp/partitions
```
Result per site: `train=120` and `val=30` images (`client_0` → Hospital A, `client_1` → Hospital B, `client_2` → Factory C). Copy only that site's `client_N/` directory to that site.

> If you use the `--dirichlet` (non-IID) option instead, check the per-client image counts first; this walkthrough used the default split only.

### 5.2 Generate each identity **at the site** (the private key never leaves it)
Run from the repository root on each edge machine:
```bash
python -c "
from packages.crypto.trustfl_crypto.keys import ClientIdentity
from pathlib import Path
ident = ClientIdentity.load_or_generate('cli_hospital_a', Path('/secure/keys/private.pem'))
print('PUBLIC_KEY_B64=' + ident.public_key_b64)
"
```
**Outputs (one per site):**
```
cli_hospital_a PUBLIC_KEY_B64=vksL/Ho2CvowMh9OxT3wXql8ernutD2eZYSk9fimjHk=
cli_hospital_b PUBLIC_KEY_B64=HgeLexLhP1AN3y3GgEXKnS0ldUFh/7XLpTFig/IQclo=
cli_factory_c  PUBLIC_KEY_B64=xmeN5OO2pvp/Jss44kTFE/lrCEDIvDzKcvt3r1b2eRk=
```
The key file is created with mode `0600`. Each operator sends their `client_id` and public key (not the file) to the coordinator operator over an authenticated channel.

### 5.3 Build the allow-list on the coordinator host
```bash
export COORDINATOR_ENROLLMENT_ALLOWLIST='{
  "cli_hospital_a": "vksL/Ho2CvowMh9OxT3wXql8ernutD2eZYSk9fimjHk=",
  "cli_hospital_b": "HgeLexLhP1AN3y3GgEXKnS0ldUFh/7XLpTFig/IQclo=",
  "cli_factory_c":  "xmeN5OO2pvp/Jss44kTFE/lrCEDIvDzKcvt3r1b2eRk="
}'
```
(Alternatively point `COORDINATOR_ENROLLMENT_ALLOWLIST_FILE` at a JSON file with the same content.)

---

## 6. Step 4 – Start the Cloud Control Plane

Run on the cloud host from the repository root. Order matters: **API migrations first, then the coordinator.**

### 6.1 API (runs the database migrations)
```bash
export PYTHONPATH=packages/schemas:packages/fl_core:packages/ml_core:packages/crypto:apps:.
export ENVIRONMENT=production
export DATABASE_URL=postgresql+psycopg://trustfl_admin:StrongPass@127.0.0.1:5432/trustfl_prod
export API_READ_KEY=<random>  API_WRITE_KEY=<random>  API_ADMIN_KEY=<random>
export COORDINATOR_PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
export CORS_ALLOWED_ORIGINS=http://127.0.0.1:3000
export IPFS_URL=http://127.0.0.1:5001 WEB3_PROVIDER_URI=http://127.0.0.1:8545

alembic -c apps/api/alembic.ini upgrade head
uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 &
```
**Output:**
```
INFO  [alembic.runtime.migration] Running upgrade  -> 3c1cda7650c5, Initial migration
INFO  [alembic.runtime.migration] Running upgrade 3c1cda7650c5 -> 7b4d1f2e5c8a, Persist coordinator rejection reason codes.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```
In production mode the API refuses to start with missing/placeholder keys, a SQLite database, a placeholder `COORDINATOR_PRIVATE_KEY`, or wildcard CORS.

### 6.2 Coordinator (Step 4 of the deployment guide + the storage and chain backends)
```bash
export ENVIRONMENT=production
export COORDINATOR_HOST=127.0.0.1
export COORDINATOR_PORT=8100
export FL_FEDERATION_ID=fed-global-vision-v1
export FL_MIN_CLIENTS=3
export FL_NUM_ROUNDS=10
export FL_ROUND_TIMEOUT_SECONDS=180.0
export FL_HEARTBEAT_TIMEOUT_SECONDS=60.0
export COORDINATOR_REQUIRE_SIGNATURES=true
export COORDINATOR_INSECURE_DEV_AUTH=false
export FL_MAX_CLIENT_WEIGHT_SHARE=0.4
export DATABASE_URL=postgresql+psycopg://trustfl_admin:StrongPass@127.0.0.1:5432/trustfl_prod
export STORAGE_BACKEND=ipfs IPFS_API_URL=http://127.0.0.1:5001 IPFS_URL=http://127.0.0.1:5001
export BLOCKCHAIN_ENABLED=true BLOCKCHAIN_RPC_URL=http://127.0.0.1:8545
export BLOCKCHAIN_CONTRACTS_JSON=$PWD/packages/contracts/deployments/localhost/contracts.json
# COORDINATOR_PRIVATE_KEY and COORDINATOR_ENROLLMENT_ALLOWLIST exported earlier

python apps/coordinator/main.py
```
**Output:**
```
INFO network.server | Restored coordinator state at round 0 (0 clients)
INFO network.server | CoordinatorServer started on 127.0.0.1:8100
INFO coordinator.main | Coordinator running: 127.0.0.1:8100  min_clients=3  num_rounds=10
```
> `FL_MAX_CLIENT_WEIGHT_SHARE=0.4` (from the guide) caps one client's weight at 40 %. With exactly 3 equal clients that is harmless; with 2 clients it would make aggregation incomplete (the cap must be ≥ 1/number-of-clients).

### 6.3 Dashboard (optional)
```bash
cd apps/dashboard
INTERNAL_API_URL=http://127.0.0.1:8000 API_READ_KEY=<same read key> \
DASHBOARD_ACCESS_KEY=<random> npx next start -H 127.0.0.1 -p 3000
```
(`next start` prints a warning that `output: standalone` prefers `node .next/standalone/server.js`; it still works.) Put it behind its own authenticated HTTPS proxy if it must be reachable remotely — see Section 11, issue 2.

---

## 7. Step 5 – Verify the Network Path From an Edge Site

Run these **from an edge site** before starting the client. Results are from Hospital A's network.

| # | Check | Command | Observed |
| :-- | :--- | :--- | :--- |
| 1 | Name resolves | `getent hosts coordinator.trustfl.test` | `198.51.100.1  coordinator.trustfl.test` |
| 2 | HTTPS works with the CA | `curl -s --cacert ca.crt https://coordinator.trustfl.test/health` | `{"status": "ok"}` HTTP 200, TLS verify OK |
| 3 | Fails without the CA (expected) | `curl -s https://coordinator.trustfl.test/health` | curl exit **60** (certificate not trusted) |
| 4 | HTTP redirects | `curl -sI http://coordinator.trustfl.test/health` | `301 → https://coordinator.trustfl.test/health` |
| 5 | Protocol | `openssl s_client -connect <host>:443 -alpn h2 -CAfile ca.crt` | `Verification: OK`, `ALPN protocol: h2` |
| 6 | Headers | `curl -sD- --cacert ca.crt .../health` | `strict-transport-security: max-age=31536000; includeSubDomains`, `x-content-type-options: nosniff`, `x-frame-options: DENY` |
| 7 | Coordinator port not exposed | TCP connect `<public-ip>:8100` | refused |
| 8 | API / dashboard not exposed | TCP connect `<public-ip>:8000`, `:3000` | refused |
| 9 | Cloud private address unreachable | TCP connect `10.20.0.10:443` from the edge | unreachable |
| 10 | Unsigned status | `curl -s --cacert ca.crt .../status` | `{"error": "authentication required"}` HTTP **401** |
| 11 | Unsigned instructions | `curl .../round/instructions/cli_hospital_a` | HTTP **401** |
| 12 | Oversized body | POST a 2 MB JSON to `/submit` | HTTP **413** (NGINX 1 MB cap) |

---

## 8. Step 6 – Start the Edge Clients & Observe the Federation

On **each edge site**, from the repository root (shown for Hospital A; change `FL_CLIENT_ID`, the key path and the data path per site):

```bash
export PYTHONPATH=packages/schemas:packages/fl_core:packages/ml_core:packages/crypto:apps:.
export ENVIRONMENT=production
export FL_CLIENT_ID=cli_hospital_a
export FL_FEDERATION_ID=fed-global-vision-v1
export FL_COORDINATOR_URL=https://coordinator.trustfl.test
export FL_IDENTITY_PATH=/secure/keys/private.pem
export FL_CA_BUNDLE=/etc/trustfl/certs/ca.crt      # only needed for a private CA
export FL_IMAGES_DIR=/data/local_partition/train/images
export FL_ANNOTATIONS_DIR=/data/local_partition/train/annotations
export FL_LOCAL_EPOCHS=2
export FL_MAX_SAMPLES=200
export FL_POLL_INTERVAL_SECONDS=5.0
export FL_NUM_CLIENTS=1        # IMPORTANT: see Section 11, issue 1

python apps/client/main.py
```

Start all three sites; the coordinator starts round 1 as soon as the third registers.

### 8.1 Edge client output (Hospital A)
```
INFO client.main | Using client identity cli_hospital_a (public key: vksL/Ho2CvowMh9OxT3wXql8ernutD2eZYSk9fimjHk=)
INFO client.main | Explicit images/annotations validated: 120 valid pairs.
INFO client.main | Using simulated detector training function on dataset: .../client_0/train/images
INFO network.agent | [cli_hospital_a] Registered with coordinator.
INFO client.main | Client cli_hospital_a connected and registered with https://coordinator.trustfl.test
...
INFO network.agent | [cli_hospital_a] Federation DONE — stopping agent.
INFO client.main | Client cli_hospital_a stopped.
```
The client process exits `0` by itself when the federation finishes.

### 8.2 Coordinator output
```
INFO network.server | Client registered: cli_hospital_a
INFO network.server | Client registered: cli_hospital_b
INFO network.server | Round 1 started with 3 clients
INFO network.server | Client registered: cli_factory_c
...
INFO coordinator.main | Training complete. 10 rounds finished.
```
10 rounds took about **70 seconds** end to end in the sandbox (no real WAN latency).

---

## 9. Verification & Live Evidence

All values below come from the 10-round run.

### 9.1 Rounds and updates (PostgreSQL)
```
rounds: round 1 … round 10 → all FINALIZED
updates by status: AGGREGATED × 30
per client: cli_hospital_a 10, cli_hospital_b 10, cli_factory_c 10
```
Mean local loss per round decreased monotonically:

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
| :--- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| Loss | 0.2240 | 0.2088 | 0.1950 | 0.1823 | 0.1708 | 0.1603 | 0.1509 | 0.1424 | 0.1348 | 0.1283 |

> The "detector" is the repository's `SimulatedDetector` (a small parameter vector trained against VisDrone box statistics). The loss is a proxy, **not** mAP, and does not measure real object-detection quality.

### 9.2 On-chain audit (123 confirmed transactions)
| Contract.function | Count | Status |
| :--- | :-: | :-- |
| `ClientRegistry.registerClient` | 3 | CONFIRMED |
| `TrainingRoundRegistry.createRound` | 10 | CONFIRMED |
| `TrainingRoundRegistry.activateRound` | 10 | CONFIRMED |
| `UpdateRegistry.submitUpdate` | 30 | CONFIRMED |
| `UpdateRegistry.markVerificationState` | 30 | CONFIRMED |
| `UpdateRegistry.recordAggregation` | 30 | CONFIRMED |
| `TrainingRoundRegistry.finalizeRound` | 10 | CONFIRMED |

### 9.3 IPFS artifacts and hash integrity
40 artifacts were recorded (30 client updates + 10 global models). Fetching the round-10 global model from IPFS and recomputing its hash:
```bash
curl -s -X POST "http://127.0.0.1:5001/api/v0/cat?arg=QmP8VBRXFijA6Vg2PqeQ6izZPBHSqZm9Afv2U6Uj2Ty7FZ" -o model.bin
sha256sum model.bin
```
```
bytes=1184
computed = sha256:122b0f5ef4e48655bc7c085a8d842c337825970301712f85733f0909ae36aa19
database = sha256:122b0f5ef4e48655bc7c085a8d842c337825970301712f85733f0909ae36aa19   ← identical
```
The same hash is the round-10 `model_version` on the dashboard's Rounds page.

### 9.4 API gateway (production auth)
```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/federations/                       # 401 (no key)
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $API_READ_KEY" http://127.0.0.1:8000/federations/   # 200
curl -s -o /dev/null -w "%{http_code}" -X POST -H "Authorization: Bearer $API_READ_KEY" \
     -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8000/federations/            # 401 (read key cannot write)
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer trustfl-read-dev" http://127.0.0.1:8000/federations/ # 401 (dev default rejected)
```
Registered clients (public keys match the allow-list):
```
cli_hospital_a True vksL/Ho2CvowMh9O…
cli_hospital_b True HgeLexLhP1AN3y3G…
cli_factory_c  True xmeN5OO2pvp/Jss4…
```
Round 10: `FINALIZED`, `model_version sha256:122b0f5e…`, global artifact `fed-global-vision-v1_global_10`.

### 9.5 Dashboard
With `DASHBOARD_ACCESS_KEY` set: no key → `401`; correct key → `200` with the federation JSON. The `/rounds`, `/clients` and `/models` pages rendered all 10 `FINALIZED` rounds, the three client IDs and their `ipfs://Qm…` artifacts. The landing page (`/`) is a client-side console that loads data after first paint, so `curl` of `/` shows "No federation selected" until the browser script runs; that is expected.

### 9.6 What the edge networks looked like to NGINX
Source addresses in the access log were only the three NAT addresses (`198.51.100.10/.11/.12`). Request mix during the 70 s main run (46 requests from each NAT address): `GET /status` 36, `POST /heartbeat` 36, `GET /round/instructions/<cid>` 33, `POST /submit` 30, `POST /register` 3 — all clients polling outbound, nothing initiated by the coordinator.

---

## 10. Failure & Security Tests Over the WAN Path

| Test | Result |
| :--- | :--- |
| Client id not in allow-list | Registration rejected; client retried 3 times then **exited code 1** after ≈16 s |
| Allowed client id, signed with a different key (impersonation) | Registration rejected; client exited code 1 |
| No `FL_CA_BUNDLE` with a private CA | TLS verification failed; client exited code 1 |
| `http://` coordinator URL in production | Refused immediately: `ValueError: Plain HTTP to 'http://coordinator.trustfl.test' is refused in production…` |
| Clock skew (signed `/status`) | +0 s, +30 s, +55 s accepted; **±120 s and +3600 s rejected (401)** — consistent with the 60 s window |
| Replay of an identical signed request | Rejected (401) |
| NGINX rate limit, 160 rapid requests from one edge IP | 26 served, 134 rejected with **503**; normal service resumed after ≈60 s |
| One site killed after round 2 (heartbeat timeout 10 s, round timeout 40 s) | Coordinator: `Quorum lost in round 4: 2 active clients < 3 required`, round 4 `FAILED`, federation aborted, coordinator **exited non-zero**; surviving clients logged `Federation ABORTED — stopping agent.` and exited |
| Hospital B's NAT router drops all forwarding for 20 s (started after round 2 finalized; round timeout 90 s) | Federation **recovered**: 8/8 rounds finalized, 24/24 updates aggregated; the outage only delayed the run |

---

## 11. Issues Found While Testing (Read Before Production)

1. **Edge sites silently train on only half of their data.**
   - The client's `FL_NUM_CLIENTS` defaults to `2`, and a client id without a digit (e.g. `cli_hospital_a`) gets partition index `0`.
   - The client then keeps only every second image (`i % 2 == 0`). In this run each site reported **`num_examples = 60`** although it held 120 training images.
   - Fix for now: set **`FL_NUM_CLIENTS=1`** on every independent edge site (verified: `num_examples = 120` for all three). The deployment guide's Step 5 does not mention this.
2. **Dashboard proxy authentication can be bypassed with a forged header.**
   - `apps/dashboard/app/api/dashboard/[...path]/route.ts` skips authentication when the request carries `Sec-Fetch-Site: same-origin` (or a `Referer` containing the host).
   - Verified with `DASHBOARD_ACCESS_KEY` set: `curl -H 'Sec-Fetch-Site: same-origin' http://127.0.0.1:3000/api/dashboard/blockchain/transactions` returned **HTTP 200 with data and no key**. (A forged `Referer` alone was rejected in this test.)
   - Do not expose the dashboard directly to the internet; put it behind an authenticating proxy and fix the route to require the key for all callers.
3. **Heartbeats are not sent while a client is training.** Local training blocks the poll loop, so training longer than `FL_HEARTBEAT_TIMEOUT_SECONDS` marks the client `OFFLINE`. With a 10 s timeout and 600 local epochs all three sites went offline and the federation aborted. Keep `FL_HEARTBEAT_TIMEOUT_SECONDS` comfortably above the slowest site's per-round training time.
4. **`/status` needs a signed request.** The "Operational Monitoring" example in the deployment guide (`curl http://localhost:8100/status`) returns `401` in production. Use a signed request (for example from a registered client's `DistributedClientAgent`) or query the API gateway instead.
5. **The Pinata option in the guide does not match the storage client.** The coordinator calls `POST {IPFS_API_URL}/api/v0/add` and `/api/v0/cat` (Kubo RPC). `https://api.pinata.cloud/psa` is not a Kubo RPC endpoint. This could not be tested without a Pinata account; use a Kubo node or IPFS Cluster that exposes the Kubo RPC API on a private address.
6. **NGINX returns 503 (not 429) when rate limiting.** Several clients behind one NAT or CGNAT address share one 120 req/min bucket (each client polls `/status`, `/heartbeat`, `/round/instructions` every `FL_POLL_INTERVAL_SECONDS`). Size `rate`/`burst` for the number of clients per public IP.

---

## 12. What Was Not Tested

- Real internet conditions (latency, loss, jitter, CGNAT, flaky mobile links) — emulated network only.
- Let's Encrypt/Certbot and a real public DNS name (a private CA was used).
- Pinata and IPFS Cluster; Tailscale/WireGuard mesh; Kubernetes ingress; cloud Postgres (Aurora/Cloud SQL).
- Docker Compose / container images (registries were unreachable from the sandbox).
- Real object-detection training (the model is simulated) and any model quality metric.
- More than 3 sites, or several clients behind one NAT.

---

## 13. Troubleshooting

| Symptom | Cause | Resolution |
| :--- | :--- | :--- |
| `Registration failed: None` then `Could not register after 3 attempts` | Coordinator unreachable (NGINX down, DNS, firewall) **or** TLS verification failing | Run the Section 7 checks; confirm `FL_CA_BUNDLE`, the certificate SAN and the `/etc/hosts`/DNS entry |
| `Registration failed` with a reachable coordinator | Client id missing from the allow-list or wrong public key | Regenerate the key, resend the public key, update `COORDINATOR_ENROLLMENT_ALLOWLIST`, restart the coordinator |
| `ValueError: Plain HTTP … refused in production` | `ENVIRONMENT=production` with non-loopback `http://` | Use `https://` |
| `curl: (60) SSL certificate problem` | Private CA not trusted | `--cacert ca.crt` / `FL_CA_BUNDLE` |
| API fails with `cannot use a string pattern on a bytes-like object` | PostgreSQL database not UTF-8 | Recreate it with `ENCODING 'UTF8'` |
| `Configuration errors: … API_READ_KEY is not configured` | Production API requires real keys and a PostgreSQL URL | Set all three API keys, `COORDINATOR_PRIVATE_KEY`, `CORS_ALLOWED_ORIGINS` |
| `Quorum lost in round N` | A site stopped heartbeating (offline, or training longer than the heartbeat timeout) | Fix the site/link; raise `FL_HEARTBEAT_TIMEOUT_SECONDS` |
| `num_examples` is half the local dataset | `FL_NUM_CLIENTS` default 2 | `FL_NUM_CLIENTS=1` on each edge site |
| Requests rejected with 401 after correct setup | Clock skew > ~60 s | Enable NTP on every host |
| `503` from NGINX under load | `limit_req` zone exceeded | Raise `rate`/`burst` |
| `pip install` fails building Pillow 10.3.0 | Python 3.13 | Use Python 3.11/3.12 |

---

## 14. Teardown
```bash
# edge sites: stop the client (it exits by itself when the federation ends) and delete test keys if not needed
# cloud host
pkill -f apps/coordinator/main.py; pkill -f "uvicorn apps.api.main"; pkill -f "next start"
sudo nginx -s stop
# remove the demo database/chain/IPFS data
sudo -u postgres psql -c "DROP DATABASE trustfl_prod;"
rm -rf packages/contracts/deployments ~/.ipfs
```
