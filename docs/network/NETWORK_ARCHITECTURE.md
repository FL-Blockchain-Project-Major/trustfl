# TrustFL Network Architecture

## Overview

Stage 04 makes TrustFL fully distributed: coordinator and clients run as
separate processes (or containers) and communicate exclusively over HTTP.
**No shared filesystem.** All training data lives on the client side.

---

## Topology

```
                 ┌─────────────────────────────────────────────┐
                 │            TrustFL Network                  │
                 │                                             │
  ┌──────────┐  HTTP  ┌───────────────────────────┐           │
  │ client_1 │◄──────►│                           │           │
  └──────────┘        │      Coordinator          │           │
                      │  host: 0.0.0.0:8100       │           │
  ┌──────────┐  HTTP  │                           │           │
  │ client_2 │◄──────►│  CoordinatorState (FSM)   │           │
  └──────────┘        │  + FedAvg aggregator      │           │
                      │  + heartbeat monitor      │           │
  ┌──────────┐  HTTP  │  + round timeout watch    │           │
  │ client_3 │◄──────►│                           │           │
  └──────────┘        └───────────────────────────┘           │
                                                               │
                 └─────────────────────────────────────────────┘
```

Clients **poll** the coordinator — the coordinator never pushes to clients.

---

## Coordinator Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/register` | Client registers; returns `{"accepted": true}` |
| `POST` | `/heartbeat` | Liveness ping; returns current server round |
| `GET`  | `/round/instructions/<cid>` | Fetch global params + active flag |
| `POST` | `/submit` | Submit local update (parameters + metrics) |
| `GET`  | `/status` | Human/monitoring status snapshot |
| `GET`  | `/health` | Docker health check endpoint |

---

## Round Lifecycle

```
clients ≥ min_clients register
         │
         ▼
   Round 1 starts (round_start_time recorded)
         │
         ├── Client polls /round/instructions/<cid>  → is_active=True
         │
         ├── Client trains locally (training_timeout enforced on client side)
         │
         ├── Client posts /submit  →  update recorded
         │
         ├── [If all active clients submitted] → aggregate immediately
         │
         └── [If round_timeout exceeded] → aggregate with partial submissions
                                            (timed_out=True recorded)

   Repeat for rounds 2..N
         │
         ▼
      DONE  (all num_rounds completed)
```

---

## Failure Modes & Mitigations

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| Client crashes mid-round | heartbeat timeout | Client evicted to OFFLINE; round continues with remaining updates on timeout |
| Client slow / busy | round_timeout_seconds | Aggregation proceeds with available updates; `timed_out=True` in history |
| Network partition | HTTP retry (3 attempts, exp back-off) | Client retries; coordinator evicts after heartbeat_timeout |
| Client reconnect | Re-registration via `/register` | Client re-registers with same `client_id`; participates in next round |
| Coordinator restart | Stateless clients re-register | Clients retry registration on next poll |

---

## Configuration Reference

### Coordinator

| Variable | Default | Description |
|----------|---------|-------------|
| `COORDINATOR_HOST` | `0.0.0.0` | Bind address |
| `COORDINATOR_PORT` | `8100` | Listen port |
| `FL_MIN_CLIENTS` | `2` | Minimum clients to start first round |
| `FL_NUM_ROUNDS` | `3` | Total training rounds |
| `FL_ROUND_TIMEOUT_SECONDS` | `60` | Per-round timeout |
| `FL_HEARTBEAT_TIMEOUT_SECONDS` | `30` | Client eviction threshold |

### Client

| Variable | Default | Description |
|----------|---------|-------------|
| `FL_CLIENT_ID` | `client_001` | Unique identifier |
| `FL_COORDINATOR_URL` | `http://127.0.0.1:8100` | Coordinator address |
| `FL_IMAGES_DIR` | — | Local dataset images directory |
| `FL_ANNOTATIONS_DIR` | — | Local dataset annotations directory |
| `FL_LOCAL_EPOCHS` | `1` | Training epochs per round |
| `FL_MAX_SAMPLES` | `50` | Max images per round |
| `FL_POLL_INTERVAL_SECONDS` | `5` | Seconds between poll cycles |

---

## TLS Readiness

The HTTP server uses Python's `http.server.HTTPServer`.  To enable TLS:

```python
import ssl
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain("/certs/server.crt", "/certs/server.key")
httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
```

Mount certificates via Docker secrets or Kubernetes `Secret` volumes.
Set `COORDINATOR_TLS_CERT` and `COORDINATOR_TLS_KEY` environment variables
(reserved for Stage 05 — blockchain/security hardening).

---

## Docker Compose — Local Multi-Service Test

```bash
# Build and start all services
docker compose -f infrastructure/docker/docker-compose.yml up --build

# Watch coordinator logs
docker logs -f trustfl-coordinator

# Stop all
docker compose -f infrastructure/docker/docker-compose.yml down
```

Dataset partitions are bind-mounted read-only from
`datasets/processed/partitions/client_00N/` into each container at `/data`.
