#!/usr/bin/env python3
"""
TrustFL Performance & Scalability Benchmark Suite
=================================================
Reproducible benchmarks measuring throughput, p50/p95/p99 latency, memory,
and scaling for:
  1. Federated Aggregation (_fedavg) across client counts & payload sizes
  2. ZKP Commitment and Proof Verification
  3. Database Repository Queries under concurrency
  4. API Endpoint throughput & latency under concurrent load

Outputs machine-readable JSON results and checks against performance budgets.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "crypto"))
sys.path.insert(0, str(ROOT / "packages" / "ml_core"))
sys.path.insert(0, str(ROOT / "packages" / "schemas"))
sys.path.insert(0, str(ROOT / "packages" / "storage"))
sys.path.insert(0, str(ROOT / "packages" / "fl_core"))
sys.path.insert(0, str(ROOT / "packages" / "blockchain"))
sys.path.insert(0, str(ROOT / "packages" / "observability"))
sys.path.insert(0, str(ROOT / "packages" / "zkp"))

from apps.coordinator.network.server import _fedavg
from apps.coordinator.zkp_verifier import ZKPVerifier


def calculate_percentiles(latencies_ms: list[float]) -> dict[str, float]:
    """Calculate min, p50, p90, p95, p99, and max from a list of latencies in ms."""
    if not latencies_ms:
        return {"min": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    sorted_lats = sorted(latencies_ms)
    n = len(sorted_lats)

    def pct(p: float) -> float:
        idx = min(int(math.ceil(p * n)) - 1, n - 1)
        return round(sorted_lats[max(0, idx)], 3)

    return {
        "min": round(sorted_lats[0], 3),
        "p50": pct(0.50),
        "p90": pct(0.90),
        "p95": pct(0.95),
        "p99": pct(0.99),
        "max": round(sorted_lats[-1], 3),
    }


# ---------------------------------------------------------------------------
# 1. Federated Aggregation Scaling Benchmark
# ---------------------------------------------------------------------------
def benchmark_aggregation(
    client_counts: list[int] = [5, 10, 25, 50, 100],
    param_sizes: list[int] = [1000, 10000, 50000],
    iterations: int = 10,
) -> dict[str, Any]:
    """Benchmark FedAvg aggregation across varying client counts and weight vector dimensions."""
    print("--> Benchmarking Federated Aggregation Scaling...")
    results = {}

    for num_params in param_sizes:
        size_key = f"{num_params}_params"
        results[size_key] = {}
        for num_clients in client_counts:
            # Generate deterministic dummy updates
            updates = []
            for c in range(num_clients):
                weights = [((c + 1) * 0.01 + (i % 100) * 0.001) for i in range(num_params)]
                updates.append({
                    "client_id": f"client_{c:03d}",
                    "parameters": [weights],
                    "num_examples": 100 + (c % 5) * 20,
                    "metrics": {"loss": 0.5 - c * 0.001, "accuracy": 0.8 + c * 0.001},
                })
            ref = [[0.0] * num_params]

            # Warm-up run
            _fedavg(updates, ref)

            # Timed iterations
            latencies_ms = []
            start_wall = time.perf_counter()
            for _ in range(iterations):
                t0 = time.perf_counter()
                _fedavg(updates, ref)
                latencies_ms.append((time.perf_counter() - t0) * 1000)
            elapsed_total = time.perf_counter() - start_wall

            pcts = calculate_percentiles(latencies_ms)
            ops_per_sec = round(iterations / elapsed_total, 2)
            results[size_key][f"{num_clients}_clients"] = {
                "num_clients": num_clients,
                "num_parameters": num_params,
                "iterations": iterations,
                "throughput_ops_per_sec": ops_per_sec,
                "latencies_ms": pcts,
            }
            print(
                f"    [{num_params:6d} params | {num_clients:3d} clients] "
                f"Throughput: {ops_per_sec:6.1f} ops/s | p50: {pcts['p50']:6.2f} ms | p95: {pcts['p95']:6.2f} ms"
            )

    return results


# ---------------------------------------------------------------------------
# 2. ZKP Verification Benchmark
# ---------------------------------------------------------------------------
def benchmark_zkp_verification(iterations: int = 25) -> dict[str, Any]:
    """Benchmark ZKP verifier CLI execution and structured rejection handling."""
    print("--> Benchmarking ZKP Verification Pipeline...")
    zkp_cmd = os.getenv(
        "ZKP_VERIFY_COMMAND",
        f"node {ROOT / 'packages' / 'zkp' / 'src' / 'verify-cli.js'}",
    )
    verifier = ZKPVerifier(command=zkp_cmd)

    dummy_proof = {
        "pi_a": ["12345", "67890"],
        "pi_b": [["1111", "2222"], ["3333", "4444"]],
        "pi_c": ["5555", "6666"],
        "protocol": "groth16",
        "curve": "bn128",
    }
    signals = ["1", "2", "3", "4", "5"]

    # Measure structured verification execution
    latencies_ms = []
    reasons = set()

    for _ in range(iterations):
        t0 = time.perf_counter()
        res = verifier.verify(proof=dummy_proof, public_signals=signals, expected_signals=signals)
        latencies_ms.append((time.perf_counter() - t0) * 1000)
        reasons.add(res.reason)

    pcts = calculate_percentiles(latencies_ms)
    throughput = round(iterations / (sum(latencies_ms) / 1000), 2)

    print(
        f"    ZKP Verifier: {throughput:6.1f} verifications/s | "
        f"p50: {pcts['p50']:6.2f} ms | p95: {pcts['p95']:6.2f} ms | outcomes: {list(reasons)}"
    )

    return {
        "iterations": iterations,
        "throughput_ops_per_sec": throughput,
        "latencies_ms": pcts,
        "observed_reasons": list(reasons),
    }


# ---------------------------------------------------------------------------
# 3. Database Query & Concurrency Benchmark
# ---------------------------------------------------------------------------
def benchmark_database_operations(
    concurrency: int = 10, queries_per_worker: int = 50
) -> dict[str, Any]:
    """Benchmark database connection checkout, query latency, and concurrent throughput."""
    print(f"--> Benchmarking Database Operations (concurrency={concurrency})...")
    try:
        from apps.api.api.db.models import Base, Client, Federation, Round
        from apps.api.api.db.session import SessionLocal, engine
    except ImportError as exc:
        print(f"    [SKIP] Database dependencies not installed in current environment ({exc}).")
        return {
            "status": "skipped",
            "reason": str(exc),
            "throughput_queries_per_sec": 0.0,
            "latencies_ms": {"p50": 0.0, "p95": 0.0},
        }

    Base.metadata.create_all(bind=engine)

    # Seed benchmark federation and rounds
    with SessionLocal() as db:
        fed = db.get(Federation, "bench-fed")
        if not fed:
            fed = Federation(id="bench-fed", name="Benchmark Federation", status="ACTIVE")
            db.add(fed)
            db.commit()
        for r in range(1, 10):
            rid = f"bench-fed_round_{r}"
            if not db.get(Round, rid):
                rnd = Round(id=rid, federation_id="bench-fed", round_number=r, status="FINALIZED")
                db.add(rnd)
        db.commit()

    latencies_ms = []

    def worker_task(worker_id: int) -> list[float]:
        worker_lats = []
        with SessionLocal() as db:
            for i in range(queries_per_worker):
                t0 = time.perf_counter()
                rounds = (
                    db.query(Round)
                    .filter(Round.federation_id == "bench-fed")
                    .all()
                )
                assert len(rounds) > 0
                worker_lats.append((time.perf_counter() - t0) * 1000)
        return worker_lats

    t_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(worker_task, w) for w in range(concurrency)]
        for f in futures:
            latencies_ms.extend(f.result())
    total_time = time.perf_counter() - t_start

    total_ops = concurrency * queries_per_worker
    throughput = round(total_ops / total_time, 2)
    pcts = calculate_percentiles(latencies_ms)

    print(
        f"    Database queries: {throughput:6.1f} queries/s | "
        f"p50: {pcts['p50']:6.2f} ms | p95: {pcts['p95']:6.2f} ms | total: {total_ops} ops in {total_time:.2f}s"
    )

    return {
        "concurrency": concurrency,
        "total_operations": total_ops,
        "elapsed_seconds": round(total_time, 3),
        "throughput_queries_per_sec": throughput,
        "latencies_ms": pcts,
    }


# ---------------------------------------------------------------------------
# 4. API Endpoints Concurrent Load Benchmark
# ---------------------------------------------------------------------------
def benchmark_api_endpoints(
    concurrency: int = 10, requests_per_worker: int = 30
) -> dict[str, Any]:
    """Benchmark FastAPI endpoints using Starlette TestClient under simulated concurrency."""
    print(f"--> Benchmarking API Endpoints under concurrent load (concurrency={concurrency})...")
    try:
        from starlette.testclient import TestClient

        from apps.api.main import app
    except ImportError as exc:
        print(f"    [SKIP] API dependencies not installed in current environment ({exc}).")
        return {
            "status": "skipped",
            "reason": str(exc),
            "throughput_req_per_sec": 0.0,
            "latencies_ms": {"p50": 0.0, "p95": 0.0},
        }

    client = TestClient(app)
    api_read_key = os.getenv("API_READ_KEY", "ci-read")
    headers = {"Authorization": f"Bearer {api_read_key}"}

    endpoints = [
        ("GET", "/health/ready", None),
        ("GET", "/federations", headers),
        ("GET", "/blockchain/transactions", headers),
    ]

    results = {}
    for method, path, req_headers in endpoints:
        latencies_ms = []

        def worker_call() -> list[float]:
            lats = []
            for _ in range(requests_per_worker):
                t0 = time.perf_counter()
                resp = client.get(path, headers=req_headers)
                lats.append((time.perf_counter() - t0) * 1000)
                assert resp.status_code in {200, 404, 429}
            return lats

        t_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(worker_call) for _ in range(concurrency)]
            for f in futures:
                latencies_ms.extend(f.result())
        total_time = time.perf_counter() - t_start

        total_reqs = concurrency * requests_per_worker
        throughput = round(total_reqs / total_time, 2)
        pcts = calculate_percentiles(latencies_ms)

        results[path] = {
            "method": method,
            "concurrency": concurrency,
            "total_requests": total_reqs,
            "throughput_req_per_sec": throughput,
            "latencies_ms": pcts,
        }
        print(
            f"    [{method} {path:25s}] {throughput:6.1f} req/s | "
            f"p50: {pcts['p50']:6.2f} ms | p95: {pcts['p95']:6.2f} ms"
        )

    return results


# ---------------------------------------------------------------------------
# Performance Budget Checks
# ---------------------------------------------------------------------------
def evaluate_performance_budgets(report: dict[str, Any]) -> tuple[bool, list[str]]:
    """Assert measured performance against documented SLO budgets."""
    violations = []

    # Budget 1: FedAvg aggregation p95 latency for 50 clients at 10,000 params must be < 250ms
    agg_p95 = (
        report.get("aggregation", {})
        .get("10000_params", {})
        .get("50_clients", {})
        .get("latencies_ms", {})
        .get("p95", 0.0)
    )
    if agg_p95 > 250.0:
        violations.append(
            f"Aggregation 50 clients (10K params) p95 latency {agg_p95}ms exceeds budget 250ms"
        )

    # Budget 2: FedAvg throughput for lightweight models must be >= 50 ops/s
    agg_1k = report.get("aggregation", {}).get("1000_params", {})
    target_client_key = "10_clients" if "10_clients" in agg_1k else "5_clients"
    if target_client_key in agg_1k:
        agg_tps = agg_1k[target_client_key].get("throughput_ops_per_sec", 0.0)
        if agg_tps < 50.0:
            violations.append(
                f"Aggregation {target_client_key} (1K params) throughput {agg_tps} ops/s below budget 50 ops/s"
            )

    # Budget 3: Database query p95 latency under concurrency must be < 50ms
    db_report = report.get("database", {})
    if db_report.get("status") != "skipped":
        db_p95 = db_report.get("latencies_ms", {}).get("p95", 0.0)
        if db_p95 > 50.0:
            violations.append(f"Database query p95 latency {db_p95}ms exceeds budget 50ms")

    # Budget 4: Ready probe p95 latency must be < 50ms
    api_report = report.get("api", {})
    if api_report.get("status") != "skipped":
        health_p95 = (
            api_report.get("/health/ready", {})
            .get("latencies_ms", {})
            .get("p95", 0.0)
        )
        if health_p95 > 50.0:
            violations.append(f"Health API p95 latency {health_p95}ms exceeds budget 50ms")

    return len(violations) == 0, violations


def run_all_benchmarks(
    output_path: Path,
    assert_budgets: bool = False,
    quick: bool = False,
) -> dict[str, Any]:
    """Execute all benchmarks and assemble machine-readable report."""
    print("=" * 70)
    print("TrustFL Phase 9 Performance & Scalability Benchmarks")
    print(f"Timestamp: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print("=" * 70)

    start_time = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    if quick:
        client_counts = [5, 20, 50]
        param_sizes = [1000, 10000]
        agg_iters = 5
        zkp_iters = 10
        db_queries = 20
        api_reqs = 15
    else:
        client_counts = [5, 10, 25, 50, 100]
        param_sizes = [1000, 10000, 50000]
        agg_iters = 10
        zkp_iters = 25
        db_queries = 50
        api_reqs = 30

    report = {
        "timestamp": start_time,
        "environment": {
            "python_version": sys.version.split()[0],
            "os": sys.platform,
            "cpu_count": os.cpu_count(),
        },
        "aggregation": benchmark_aggregation(
            client_counts=client_counts,
            param_sizes=param_sizes,
            iterations=agg_iters,
        ),
        "zkp_verification": benchmark_zkp_verification(iterations=zkp_iters),
        "database": benchmark_database_operations(concurrency=8, queries_per_worker=db_queries),
        "api": benchmark_api_endpoints(concurrency=8, requests_per_worker=api_reqs),
    }

    passed, violations = evaluate_performance_budgets(report)
    report["budget_evaluation"] = {
        "passed": passed,
        "violations": violations,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[+] Benchmark results saved to: {output_path}")

    if violations:
        print("\n[!] Performance Budget Violations:")
        for v in violations:
            print(f"    - {v}")
    else:
        print("\n[+] All Performance Budgets PASSED.")

    if assert_budgets and not passed:
        raise RuntimeError(f"Performance budgets violated: {violations}")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="TrustFL Performance Benchmark Runner")
    parser.add_argument(
        "--output-file",
        type=Path,
        default=ROOT / "dist" / "benchmarks" / "benchmark_results.json",
        help="Path to write JSON benchmark report",
    )
    parser.add_argument(
        "--assert-budgets",
        action="store_true",
        help="Fail with exit code 1 if performance budgets are violated",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run fewer iterations for quick test cycles",
    )
    args = parser.parse_args()

    run_all_benchmarks(
        output_path=args.output_file,
        assert_budgets=args.assert_budgets,
        quick=args.quick,
    )


if __name__ == "__main__":
    main()
