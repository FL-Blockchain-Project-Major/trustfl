# TrustFL Multi-Device & Network Deployment Guide

This document provides production-ready, step-by-step instructions for orchestrating TrustFL across three core deployment topologies:

1. **[Scenario A: Same Device, Same Network (Localhost / Single-Host Docker)](#scenario-a-same-device-under-same-network)**
2. **[Scenario B: Different Devices, Same Network (Local Area Network / On-Premise LAN)](#scenario-b-different-devices-under-same-network-lan)**
3. **[Scenario C: Different Devices, Different Networks (Wide Area Network / Internet / Edge-to-Cloud)](#scenario-c-different-devices-under-different-networks-wan--internet)**

---

## 🏛 TrustFL Network Topology & Traffic Flow

Before configuring hosts, understand TrustFL's communication model:

```
               ┌────────────────────────────────────────────────────────┐
               │              TRUSTFL CONTROL PLANE                     │
               │                                                        │
               │   ┌────────────────────┐      ┌────────────────────┐   │
               │   │ Next.js Dashboard  │      │  FastAPI Backend   │   │
               │   │  (Port 3000)       │◄────►│   (Port 8000)      │   │
               │   └────────────────────┘      └─────────┬──────────┘   │
               │                                         │              │
               │   ┌────────────────────┐      ┌─────────▼──────────┐   │
               │   │ IPFS / Object Store│      │    Coordinator     │   │
               │   │  (Port 5001/8081)  │◄────►│  (HTTP/S: 8100/443)│   │
               │   └────────────────────┘      └─────────▲──────────┘   │
               └─────────────────────────────────────────┼──────────────┘
                                                         │
                             POLLING ONLY (HTTP/S)       │
                 ┌───────────────────────────────────────┴───────────────────────────────────────┐
                 │                                       │                                       │
      ┌──────────┴───────────┐                ┌──────────┴───────────┐                ┌──────────┴───────────┐
      │     Client Node 1    │                │     Client Node 2    │                │     Client Node 3    │
      │ (Local Data & Model) │                │ (Local Data & Model) │                │ (Local Data & Model) │
      └──────────────────────┘                └──────────────────────┘                └──────────────────────┘
```

### Critical Networking Invariants:
1. **Unidirectional Polling**: Edge clients initiate all HTTP(S) requests. The coordinator **never connects outbound to clients**. Clients behind NAT, CGNAT, or strict enterprise firewalls do not require inbound open ports or port forwarding.
2. **Production TLS Enforcement**: When `ENVIRONMENT=production`, the client agent **strictly refuses** plain `http://` coordinator URLs unless targeting a loopback address (`127.0.0.1`, `localhost`, `::1`). Non-loopback network calls require `https://`.
3. **Replay & Timing Protection**: Requests are signed using the client's Ed25519 private key and stamped with UNIX timestamps (`X-TrustFL-Timestamp`). System clocks across coordinator and client hosts must be synchronized (NTP) within **60 seconds**, or requests are rejected with `TIMESTAMP_DRIFT`.

---

## Scenario A: Same Device Under Same Network

Use Scenario A for local algorithm validation, debugging, and single-server continuous integration.

### Method A1: Automated Docker Compose (Recommended)

The root `docker-compose.yml` launches PostgreSQL, IPFS, a local Hardhat blockchain, contract deployer, FastAPI control plane, coordinator, dashboard, and 2 simulated clients.

#### Step 1: Initialize Environment
```bash
cp .env.example .env
```
Ensure `.env` contains:
```bash
ENVIRONMENT=development
COORDINATOR_PORT=8100
FL_MIN_CLIENTS=2
FL_NUM_ROUNDS=3
COORDINATOR_INSECURE_DEV_AUTH=true
STORAGE_BACKEND=ipfs
BLOCKCHAIN_ENABLED=true
```

#### Step 2: Build and Launch Stack
```bash
docker compose up --build -d
```

#### Step 3: Verify Container Health
```bash
docker compose ps
```
All services (`db`, `ipfs`, `hardhat`, `contract-deployer`, `api`, `coordinator`, `client-1`, `client-2`, `dashboard`) should show `healthy` or `exited (0)` for the contract deployer.

#### Step 4: Inspect Live Training Logs
```bash
docker compose logs -f coordinator
```
You will observe:
```text
coordinator | Coordinator running: 0.0.0.0:8100 min_clients=2 num_rounds=3
client-1    | [client_001] Registered with coordinator.
client-2    | [client_002] Registered with coordinator.
coordinator | Round 1 started.
coordinator | Round 1 aggregated successfully.
...
coordinator | Training complete. 3 rounds finished.
```

Access the UI at `http://localhost:3000` and API documentation at `http://localhost:8000/docs`.

---

### Method A2: Native Python CLI Processes

Run each component as independent terminal processes on your machine.

#### Step 1: Install Dependencies
```bash
make install
source .venv/bin/activate
```

#### Step 2: Provision Client Cryptographic Identities
```bash
mkdir -p /tmp/trustfl-keys/client_001 /tmp/trustfl-keys/client_002

python3 -c "
from packages.crypto.trustfl_crypto.keys import ClientIdentity
from pathlib import Path
import json

c1 = ClientIdentity.load_or_generate('client_001', Path('/tmp/trustfl-keys/client_001/private.pem'))
c2 = ClientIdentity.load_or_generate('client_002', Path('/tmp/trustfl-keys/client_002/private.pem'))
allowlist = {'client_001': c1.public_key_b64, 'client_002': c2.public_key_b64}
print('ALLOWLIST_JSON=' + json.dumps(allowlist))
" > /tmp/trustfl-keys/allowlist.env

source /tmp/trustfl-keys/allowlist.env
```

#### Step 3: Start Coordinator (Terminal 1)
```bash
export PYTHONPATH=packages/schemas:packages/fl_core:packages/ml_core:packages/crypto:apps:.
export COORDINATOR_HOST=127.0.0.1
export COORDINATOR_PORT=8100
export FL_MIN_CLIENTS=2
export FL_NUM_ROUNDS=2
export COORDINATOR_REQUIRE_SIGNATURES=true
export COORDINATOR_ENROLLMENT_ALLOWLIST=$ALLOWLIST_JSON
export STORAGE_BACKEND=local
export STORAGE_LOCAL_DIR=/tmp/trustfl-artifacts

python3 apps/coordinator/main.py
```

#### Step 4: Start Client 1 (Terminal 2)
```bash
export PYTHONPATH=packages/schemas:packages/fl_core:packages/ml_core:packages/crypto:apps:.
export FL_CLIENT_ID=client_001
export FL_COORDINATOR_URL=http://127.0.0.1:8100
export FL_IDENTITY_PATH=/tmp/trustfl-keys/client_001/private.pem
export FL_POLL_INTERVAL_SECONDS=2.0

python3 apps/client/main.py
```

#### Step 5: Start Client 2 (Terminal 3)
```bash
export PYTHONPATH=packages/schemas:packages/fl_core:packages/ml_core:packages/crypto:apps:.
export FL_CLIENT_ID=client_002
export FL_COORDINATOR_URL=http://127.0.0.1:8100
export FL_IDENTITY_PATH=/tmp/trustfl-keys/client_002/private.pem
export FL_POLL_INTERVAL_SECONDS=2.0

python3 apps/client/main.py
```

---

## Scenario B: Different Devices Under Same Network (LAN)

In this scenario, all physical nodes (e.g. workstations, GPU rigs, laptops) reside on the same Local Area Network (subnet `192.168.1.0/24`).

```
                    LOCAL AREA NETWORK (192.168.1.0/24)
  ┌────────────────────────────────────────────────────────────────────────┐
  │                                                                        │
  │   Coordinator Host                                Client Host 1        │
  │   IP: 192.168.1.50                                IP: 192.168.1.101    │
  │   Port: 8100 (HTTPS)                              Client: client_001   │
  │   Storage / DB                                                         │
  │          ▲                                               │             │
  │          │                                               │             │
  │          └───────────────────────────────────────────────┤             │
  │          │         HTTPS Requests (LAN Direct)           │             │
  │          ▲                                                             │
  │          │                                        Client Host 2        │
  │          │                                        IP: 192.168.1.102    │
  │          └────────────────────────────────────────Client: client_002   │
  └────────────────────────────────────────────────────────────────────────┘
```

### Pre-requisites & IP Allocation:
- **Coordinator Host**: Static or DHCP-reserved IP: `192.168.1.50`
- **Client Host 1**: IP: `192.168.1.101`
- **Client Host 2**: IP: `192.168.1.102`

---

### Step 1: Open Firewall Ports on Coordinator Host
On the Coordinator machine (`192.168.1.50`):
```bash
# For Ubuntu / Debian (UFW)
sudo ufw allow 8100/tcp comment "TrustFL Coordinator"
sudo ufw allow 8000/tcp comment "TrustFL API"
sudo ufw allow 3000/tcp comment "TrustFL Dashboard"

# For RHEL / Fedora / CentOS (firewalld)
sudo firewall-cmd --permanent --add-port=8100/tcp
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

---

### Step 2: Configure TLS Certificates (LAN PKI)

Because `ENVIRONMENT=production` rejects plain HTTP across physical networks, generate a TLS certificate with Subject Alternative Name (SAN) covering the coordinator's LAN IP:

On the Coordinator machine:
```bash
mkdir -p /etc/trustfl/certs
cd /etc/trustfl/certs

# Generate CA Key and Root Certificate
openssl req -x509 -new -nodes -keyout ca.key -sha256 -days 365 -out ca.crt \
    -subj "/C=US/ST=Security/O=TrustFL CA/CN=TrustFL-Root-CA"

# Create OpenSSL SAN configuration for LAN IP
cat > san.cnf <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
O = TrustFL
CN = 192.168.1.50

[v3_req]
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
IP.1 = 192.168.1.50
DNS.1 = coordinator.local
EOF

# Generate Server CSR and Sign with CA
openssl req -new -newkey rsa:2048 -nodes -keyout server.key -out server.csr -config san.cnf
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out server.crt -days 365 -sha256 -extfile san.cnf -extensions v3_req

sudo chmod 600 server.key ca.key
```

Copy `ca.crt` to every client device (`/etc/trustfl/certs/ca.crt`).

---

### Step 3: Enroll Client Identities on Coordinator Host

On each Client Machine, generate its Ed25519 identity key:
```bash
# Run on Client Host 1 (192.168.1.101):
python3 -c "
from packages.crypto.trustfl_crypto.keys import ClientIdentity
from pathlib import Path
ident = ClientIdentity.load_or_generate('client_001', Path('/etc/trustfl/client_key.pem'))
print(f'CLIENT_001_PUBKEY={ident.public_key_b64}')
"
```
```bash
# Run on Client Host 2 (192.168.1.102):
python3 -c "
from packages.crypto.trustfl_crypto.keys import ClientIdentity
from pathlib import Path
ident = ClientIdentity.load_or_generate('client_002', Path('/etc/trustfl/client_key.pem'))
print(f'CLIENT_002_PUBKEY={ident.public_key_b64}')
"
```

Collect the output strings and configure the Coordinator's enrollment allowlist:
```bash
export COORDINATOR_ENROLLMENT_ALLOWLIST='{
  "client_001": "<CLIENT_001_PUBKEY_OUTPUT>",
  "client_002": "<CLIENT_002_PUBKEY_OUTPUT>"
}'
```

---

### Step 4: Start Coordinator with TLS (Coordinator Host)
```bash
export ENVIRONMENT=production
export COORDINATOR_HOST=0.0.0.0
export COORDINATOR_PORT=8100
export FL_FEDERATION_ID=fed-lan-01
export FL_MIN_CLIENTS=2
export FL_NUM_ROUNDS=5
export COORDINATOR_REQUIRE_SIGNATURES=true
export COORDINATOR_INSECURE_DEV_AUTH=false
export COORDINATOR_TLS_CERT=/etc/trustfl/certs/server.crt
export COORDINATOR_TLS_KEY=/etc/trustfl/certs/server.key
export STORAGE_BACKEND=local
export STORAGE_LOCAL_DIR=/var/lib/trustfl/artifacts

python3 apps/coordinator/main.py
```

---

### Step 5: Start Clients (Client Hosts)

#### On Client Host 1 (`192.168.1.101`):
```bash
export ENVIRONMENT=production
export FL_CLIENT_ID=client_001
export FL_FEDERATION_ID=fed-lan-01
export FL_COORDINATOR_URL=https://192.168.1.50:8100
export FL_IDENTITY_PATH=/etc/trustfl/client_key.pem
export FL_CA_BUNDLE=/etc/trustfl/certs/ca.crt
export FL_LOCAL_EPOCHS=2
export FL_MAX_SAMPLES=100
export FL_POLL_INTERVAL_SECONDS=3.0

python3 apps/client/main.py
```

#### On Client Host 2 (`192.168.1.102`):
```bash
export ENVIRONMENT=production
export FL_CLIENT_ID=client_002
export FL_FEDERATION_ID=fed-lan-01
export FL_COORDINATOR_URL=https://192.168.1.50:8100
export FL_IDENTITY_PATH=/etc/trustfl/client_key.pem
export FL_CA_BUNDLE=/etc/trustfl/certs/ca.crt
export FL_LOCAL_EPOCHS=2
export FL_MAX_SAMPLES=100
export FL_POLL_INTERVAL_SECONDS=3.0

python3 apps/client/main.py
```

---

## Scenario C: Different Devices Under Different Networks (WAN / Internet)

This is the standard cross-organizational enterprise architecture: the Coordinator runs in a cloud VPC (AWS, GCP, Azure, or Kubernetes), while Edge Clients operate across diverse locations (hospitals, factories, edge gateways) traversing NAT firewalls over the public Internet.

```
       REMOTE EDGE CLIENTS                                 PUBLIC INTERNET & CLOUD VPC
  ┌───────────────────────────┐                         ┌────────────────────────────────────────┐
  │ Hospital A                │                         │ AWS / GCP / Kubernetes Ingress         │
  │ Client ID: cli_hospital_a │                         │ Domain: coordinator.trustfl.io         │
  │ Behind NAT (No Open Port) │                         │                                        │
  │                           │                         │  ┌──────────────────────────────────┐  │
  │ Sends HTTPS Outbound ─────┼───(Public Internet)────►│  │ NGINX / Cloudflare TLS Proxy     │  │
  └───────────────────────────┘                         │  │ - Port 443 (Let's Encrypt SSL)   │  │
                                                        │  │ - Rate Limiting & HSTS           │  │
  ┌───────────────────────────┐                         │  └──────────────────┬───────────────┘  │
  │ Hospital B                │                         │                     │                  │
  │ Client ID: cli_hospital_b │                         │                     ▼ HTTP (Private)   │
  │ Behind NAT (No Open Port) │                         │  ┌──────────────────────────────────┐  │
  │                           │                         │  │ TrustFL Coordinator Singleton    │  │
  │ Sends HTTPS Outbound ─────┼───(Public Internet)────►│  │ - Port 8100                      │  │
  └───────────────────────────┘                         │  │ - Verified Allowlist & Signatures│  │
                                                        │  └──────────────────┬───────────────┘  │
  ┌───────────────────────────┐                         │                     │                  │
  │ Factory C                 │                         │       ┌─────────────┴────────────┐     │
  │ Client ID: cli_factory_c  │                         │       ▼                          ▼     │
  │ Behind NAT (No Open Port) │                         │  PostgreSQL Cluster       IPFS Gateway │
  │ Sends HTTPS Outbound ─────┼───(Public Internet)────►│  (Aurora / Cloud SQL)   (Pinata/Kubo)  │
  └───────────────────────────┘                         └────────────────────────────────────────┘
```

---

### Step 1: Cloud Coordinator DNS & Ingress Configuration

1. Provision a public domain name, e.g.: `coordinator.trustfl.io`.
2. Configure DNS `A` or `CNAME` record pointing `coordinator.trustfl.io` to your Cloud Load Balancer or VM public IP.
3. Terminate TLS at NGINX using Let's Encrypt (Certbot).

#### Production NGINX Reverse Proxy Configuration (`/etc/nginx/sites-available/trustfl.conf`):
```nginx
# Rate limiting zone: max 120 requests per minute per IP
limit_req_zone $binary_remote_addr zone=trustfl_limit:10m rate=120r/m;

server {
    listen 80;
    server_name coordinator.trustfl.io api.trustfl.io;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name coordinator.trustfl.io;

    ssl_certificate /etc/letsencrypt/live/coordinator.trustfl.io/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/coordinator.trustfl.io/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Enforce HTTP Strict Transport Security (HSTS)
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;

    # TrustFL body size limit: 1 MB matches MAX_BODY_BYTES in coordinator
    client_max_body_size 1M;

    location / {
        limit_req zone=trustfl_limit burst=20 nodelay;

        proxy_pass http://127.0.0.1:8100;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        # Keepalive settings for low latency polling
        proxy_read_timeout 90s;
        proxy_connect_timeout 10s;
    }
}
```

Enable configuration and restart NGINX:
```bash
sudo ln -s /etc/nginx/sites-available/trustfl.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

### Step 2: Cloud Storage Setup for WAN (IPFS / Pinata)

Across WAN, clients cannot access local filesystem mounts. Use a decentralized IPFS cluster or Pinata endpoint:
```bash
# In coordinator production .env:
STORAGE_BACKEND=ipfs
IPFS_API_URL=https://api.pinata.cloud/psa   # or internal cluster http://ipfs-cluster:5001
IPFS_CONNECT_TIMEOUT_SECONDS=10
IPFS_READ_TIMEOUT_SECONDS=60
```

---

### Step 3: Provision Edge Client Credentials & Allowlist

For each edge participant, generate keys locally at the edge site.

#### On Edge Client A (Hospital A):
```bash
python3 -c "
from packages.crypto.trustfl_crypto.keys import ClientIdentity
from pathlib import Path
ident = ClientIdentity.load_or_generate('cli_hospital_a', Path('/secure/keys/private.pem'))
print('PUBLIC_KEY_B64=' + ident.public_key_b64)
"
```
The client operator securely transmits `cli_hospital_a` and its `PUBLIC_KEY_B64` to the federation coordinator operator.

#### On Coordinator Host:
Add all participant public keys to `COORDINATOR_ENROLLMENT_ALLOWLIST`:
```bash
export COORDINATOR_ENROLLMENT_ALLOWLIST='{
  "cli_hospital_a": "kE9z1w5G1A...hospital_a_key...",
  "cli_hospital_b": "M8x42b99Qw...hospital_b_key...",
  "cli_factory_c":  "Z3q10oP88v...factory_c_key..."
}'
```

---

### Step 4: Run Cloud Coordinator Daemon
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
export DATABASE_URL=postgresql+psycopg://trustfl_admin:StrongPass@postgres.vpc.internal:5432/trustfl_prod

python3 apps/coordinator/main.py
```

---

### Step 5: Run Edge Clients Across the World

Edge clients do **not** need VPN, port forwarding, or public IP addresses. They require only outbound internet access on port 443.

#### On Edge Client A:
```bash
export ENVIRONMENT=production
export FL_CLIENT_ID=cli_hospital_a
export FL_FEDERATION_ID=fed-global-vision-v1
export FL_COORDINATOR_URL=https://coordinator.trustfl.io
export FL_IDENTITY_PATH=/secure/keys/private.pem
export FL_IMAGES_DIR=/data/local_partition/images
export FL_ANNOTATIONS_DIR=/data/local_partition/annotations
export FL_LOCAL_EPOCHS=2
export FL_MAX_SAMPLES=200
export FL_POLL_INTERVAL_SECONDS=5.0

python3 apps/client/main.py
```

#### On Edge Client B:
```bash
export ENVIRONMENT=production
export FL_CLIENT_ID=cli_hospital_b
export FL_FEDERATION_ID=fed-global-vision-v1
export FL_COORDINATOR_URL=https://coordinator.trustfl.io
export FL_IDENTITY_PATH=/secure/keys/private.pem
export FL_IMAGES_DIR=/data/local_partition/images
export FL_ANNOTATIONS_DIR=/data/local_partition/annotations
export FL_LOCAL_EPOCHS=2
export FL_MAX_SAMPLES=200
export FL_POLL_INTERVAL_SECONDS=5.0

python3 apps/client/main.py
```

---

### Alternative WAN Option: Zero-Trust Mesh (Tailscale / WireGuard)

For private consortiums that prefer not to publish the coordinator on the public Internet, deploy an encrypted overlay mesh network:

1. Install **Tailscale** on the Coordinator VM and all Edge Workers.
2. Join the same Tailnet: `sudo tailscale up`.
3. Note the Coordinator's private mesh IP, e.g., `100.80.20.10`.
4. Run Coordinator bound to `100.80.20.10:8100`.
5. Run Edge Clients targeting `https://100.80.20.10:8100` (or `http://` if using Tailscale MagicDNS certificates with TLS).

---

## Operational Monitoring & Troubleshooting Guide

### 1. Verification of Registration & Status
Query the coordinator's status endpoint from an authorized host:
```bash
curl -s http://localhost:8100/status | jq .
```
Expected output:
```json
{
  "status": "ROUND_ACTIVE",
  "current_round": 1,
  "num_rounds": 5,
  "active_clients": ["client_001", "client_002"],
  "round_history": [],
  "finalization": {
    "pending": false,
    "attempts": 0,
    "next_retry_at": null,
    "terminal_error": null
  }
}
```

### 2. Common Errors and Resolution

| Symptom | Root Cause | Solution |
| :--- | :--- | :--- |
| `ValueError: Plain HTTP to 'http://...' is refused in production` | Client is in `ENVIRONMENT=production` targeting non-loopback `http://`. | Switch URL to `https://` or supply TLS termination proxy. |
| `Registration failed: {"accepted": false}` | Client ID missing from `COORDINATOR_ENROLLMENT_ALLOWLIST` or public key mismatch. | Re-generate public key and verify JSON string in coordinator allowlist. |
| `413 Request Entity Too Large` | Client update payload exceeds `MAX_BODY_BYTES = 1,048,576` (1 MB). | Ensure weights are simulated (`SimulatedDetector`) or parameter representations are compressed. |
| `TIMESTAMP_DRIFT` | Edge device clock differs from coordinator by $>60$ seconds. | Synchronize system clock via NTP: `sudo timedatectl set-ntp true` or `ntpdate pool.ntp.org`. |
| `Quorum lost in round N: X active clients < Y required` | One or more clients stopped heartbeating, causing active clients to fall below `FL_MIN_CLIENTS`. | Check network connectivity on edge devices; increase `FL_HEARTBEAT_TIMEOUT_SECONDS` if edge compute is overloaded. |
| `Dashboard API is unavailable (503)` | Next.js server cannot reach FastAPI or read key is invalid. | Verify `INTERNAL_API_URL` and `API_READ_KEY` match the FastAPI configuration. |

