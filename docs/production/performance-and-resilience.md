# TrustFL Performance, Scalability & Resilience Architecture

## 1. Executive Summary & SLOs

TrustFL Phase 9 establishes measurable performance benchmarks, scalability limits, and fault-injection resilience guarantees across the coordinator, API control-plane, zero-knowledge proof verification pipeline, and blockchain transaction anchoring layer.

### Service Level Objectives (SLOs) & Performance Budgets

| Metric / Boundary | Target / Budget | Measured Baseline | Status |
| :--- | :--- | :--- | :--- |
| **API Health / Readiness (`/health/ready`) p95** | `< 50 ms` | `2.8 ms` | ✅ Compliant |
| **FedAvg Aggregation (50 clients, 10k params) p95** | `< 250 ms` | `115.4 ms` | ✅ Compliant |
| **FedAvg Aggregation Throughput (10 clients, 1k params)**| `> 50 ops/s` | `403.0 ops/s` | ✅ Compliant |
| **ZKP Proof Verification CLI (Groth16/BN128) p95** | `< 2000 ms` | `1747.5 ms` | ✅ Compliant |
| **Database Control-Plane Query Latency p95** | `< 50 ms` | `4.2 ms` | ✅ Compliant |
| **Maximum Request Body Size (`API_MAX_BODY_BYTES`)** | `1 MB` (Strict) | Enforced by Middleware | ✅ Compliant |
| **Maximum Proof Payload Size (`API_MAX_PROOF_BYTES`)** | `256 KB` (Strict) | Enforced by Middleware | ✅ Compliant |

---

## 2. Empirical Benchmark Baselines

All figures are generated using the reproducible benchmark runner (`scripts/run_benchmarks.py`).

### 2.1 Federated Aggregation Scaling (`_fedavg`)

Evaluated with L2 norm delta clipping and client weight-share capping (`FL_MAX_CLIENT_WEIGHT_SHARE=0.5`):

| Model Parameters (Weights) | Client Count | Throughput (ops/s) | p50 Latency (ms) | p95 Latency (ms) |
| :--- | :--- | :--- | :--- | :--- |
| **1,000 parameters** | 5 clients | 742.9 ops/s | 1.27 ms | 2.01 ms |
| | 10 clients | 403.0 ops/s | 2.40 ms | 2.92 ms |
| | 25 clients | 194.0 ops/s | 5.09 ms | 5.88 ms |
| | 50 clients | 91.7 ops/s | 10.99 ms | 12.36 ms |
| | 100 clients | 46.5 ops/s | 20.89 ms | 23.05 ms |
| **10,000 parameters** | 5 clients | 85.2 ops/s | 11.23 ms | 14.84 ms |
| | 10 clients | 46.2 ops/s | 21.26 ms | 25.58 ms |
| | 25 clients | 18.9 ops/s | 52.45 ms | 55.84 ms |
| | 50 clients | 9.2 ops/s | 109.77 ms | 115.39 ms |
| | 100 clients | 4.7 ops/s | 217.90 ms | 226.01 ms |
| **50,000 parameters** | 5 clients | 18.9 ops/s | 52.86 ms | 55.58 ms |
| | 10 clients | 10.1 ops/s | 92.28 ms | 115.77 ms |
| | 25 clients | 3.8 ops/s | 258.38 ms | 331.03 ms |
| | 50 clients | 1.9 ops/s | 526.95 ms | 632.23 ms |
| | 100 clients | 1.0 ops/s | 997.25 ms | 1089.11 ms |

### 2.2 ZKP Verification Execution Pipeline

The ZKP verification pipeline invokes the Groth16 BN128 verifier CLI (`packages/zkp/src/verify-cli.js`) to cryptographically validate Poseidon update commitments against the circuit verification key:

- **CLI Throughput:** `0.70 ops/s` (single-threaded sub-process execution)
- **p50 Latency:** `1475.0 ms`
- **p95 Latency:** `1747.5 ms`
- **Failure Rejection:** Fail-closed on invalid public inputs or corrupt proof signals.

---

## 3. Scalability Controls & Resource Bounds

TrustFL applies defense-in-depth resource bounding to prevent Denial of Service (DoS), memory exhaustion, and connection starvation under high concurrency.

### 3.1 Bounded Request Streaming & Payload Caps

- **Request Size Limiting (`RequestSizeLimitMiddleware`):**
  - General API mutating routes: capped at **1 MB** (`MAX_BODY_BYTES`).
  - Proof submission routes (`/proof`): capped at **256 KB** (`MAX_PROOF_BODY_BYTES`).
  - Oversized payloads receive `HTTP 413 Payload Too Large` immediately without reading into memory.
- **Client Weight-Share Capping (`FL_MAX_CLIENT_WEIGHT_SHARE`):**
  - Capped at `0.50` by default. No single enrolled client can claim more than 50% of the aggregated round weight regardless of self-reported example count.
- **L2 Norm Clipping (`FL_MAX_UPDATE_NORM`):**
  - Prevents model poisoning by bounding the L2 distance of incoming updates from the reference global model.

### 3.2 Database Connection Pool Sizing

Database pooling is configured in `apps/api/api/db/session.py` with explicit bounds and health pre-pinging:

```python
engine_kwargs = {
    "pool_size": int(os.getenv("DB_POOL_SIZE", "20")),
    "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
    "pool_timeout": float(os.getenv("DB_POOL_TIMEOUT", "30.0")),
    "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
    "pool_pre_ping": True,
}
```

- `pool_pre_ping=True`: Tests connections before handing them to requests, transparently reconnecting after PostgreSQL server restarts or network blips.
- `pool_size=20`, `max_overflow=10`: Accommodates up to 30 concurrent database workers per instance without connection pool exhaustion.

### 3.3 Distributed Rate Limiting & Backpressure

The `RateLimitMiddleware` enforces sliding-window rate limits via Redis (or thread-safe in-memory sliding window):
- General API: `100/minute`
- Model update submissions: `30/minute`
- ZKP proof submissions: `10/minute`
- Exceeded limits return `HTTP 429 Too Many Requests` with RFC-compliant `Retry-After` header.

---

## 4. Resilience & Fault-Injection Recovery Matrix

| Fault Scenario | Trigger / Condition | System Recovery Behavior | Guarantee |
| :--- | :--- | :--- | :--- |
| **Coordinator Crash & Restart** | Process termination or container restart mid-training | Coordinator calls `restore_state()`, re-registers active clients, restores current round number, reload global model artifact from storage, and resumes lifecycle without duplicating round numbers. | Zero data loss; state consistency. |
| **PostgreSQL Disconnection** | DB restart, failover, or network split | `pool_pre_ping=True` detects dropped connections and automatically reconnects; active transactions rollback cleanly. | ACID isolation maintained. |
| **Blockchain RPC Timeout / Failure** | RPC endpoint latency spike or network partition | `_chain_call_with_retry` and `BlockchainOutbox` retry with exponential backoff up to `CHAIN_CALL_MAX_RETRIES`. Finalization retries up to `FINALIZE_MAX_RETRIES`. | Zero duplicate aggregation; eventual on-chain consistency. |
| **Replayed Client Updates** | Adversary re-submits previously observed signed update | Verifier rejects nonce reuse; coordinator rejects duplicate submission from enrolled client within same round. | Idempotent rejection; no double-counting. |
| **Split-Brain / Multi-Instance Race** | Two coordinator processes attempt to control the same federation | `CoordinatorLease.acquire_lease()` uses `with_for_update()` and fencing tokens; secondary instance is locked out until lease TTL expires. | Mutual exclusion; zero dual-aggregation. |
| **Client Quorum Loss** | Heartbeat timeout drops active clients below `min_clients` | Heartbeat monitor aborts or pauses round (`status=FAILED`); does not emit unbacked aggregated models. | Fail-closed consensus. |

---

## 5. Local Reproduction Commands

### Run Full Benchmark Suite

```bash
# Execute complete benchmarks and assert against performance budgets
python3 scripts/run_benchmarks.py --assert-budgets

# Output JSON report:
cat dist/benchmarks/benchmark_results.json
```

### Run Phase 9 Deterministic Regression Tests

```bash
# Performance & scalability tests
pytest tests/unit/test_phase9_performance.py

# Resilience & fault injection tests
pytest tests/unit/test_phase9_resilience.py
```

### Run Full CI Test Suite

```bash
# Run complete test suite
pytest tests/
```

---

## 6. Known Limitations & Capacity Assumptions

1. **ZKP Verification Throughput:** Groth16 circuit verification in Node.js/snarkjs consumes ~1.4s per verification. Under high client concurrency (>100 clients per round), proof verification should be batched or offloaded to a worker queue.
2. **Horizontal Coordinator Scaling:** Active coordination within a single federation requires a single leader holding the `CoordinatorLease`. Multiple federations can run concurrently across independent coordinator instances.
3. **Database Backend:** SQLite is strictly for development and local testing. Production environments must configure PostgreSQL with `DB_POOL_SIZE >= 20` and Redis for distributed rate limiting.
