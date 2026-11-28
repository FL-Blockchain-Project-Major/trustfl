"""Phase 14 HA, Disaster Recovery & Operational Resilience integration tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class _MockIPFSHandler(BaseHTTPRequestHandler):
    store: dict[str, bytes] = {}
    pinned: set[str] = set()

    def log_message(self, _format: str, *_args) -> None:
        return

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length > 0 else b""
        if parsed.path == "/api/v0/add":
            # Extract multipart file bytes between the first double CRLF and trailing boundary
            raw = body
            if b"\r\n\r\n" in raw:
                raw = raw.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
            cid = "Qm" + hashlib.sha256(raw).hexdigest()[:44]
            self.__class__.store[cid] = raw
            qs = parse_qs(parsed.query)
            if qs.get("pin", ["true"])[0] == "true":
                self.__class__.pinned.add(cid)
            resp = json.dumps({"Hash": cid}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        if parsed.path == "/api/v0/cat":
            qs = parse_qs(parsed.query)
            cid = qs.get("arg", [""])[0]
            if cid not in self.__class__.store:
                self.send_response(404)
                self.end_headers()
                return
            data = self.__class__.store[cid]
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_response(404)
        self.end_headers()


def _start_mock_ipfs():
    class Handler(_MockIPFSHandler):
        store = {}
        pinned = set()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, Handler, f"http://127.0.0.1:{srv.server_port}"


class TestPhase14HADR(unittest.TestCase):
    """Phase 14 HA, backup/restore, lease fencing, failover, and alerting tests."""

    def test_authenticated_backup_envelope_rejects_tampering_and_wrong_key(self) -> None:
        if not shutil.which("sha256sum"):
            self.skipTest("Requires sha256sum in PATH")

        from apps.api.api.db.models import Base, Federation, FederationStatus, Round, RoundStatus

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "trustfl.db"
            backup_path = root / "trustfl-backup.db.enc"
            manifest_path = Path(f"{backup_path}.sha256")
            key_file = root / "backup.key"
            key_file.write_text("11" * 32, encoding="utf-8")

            engine = create_engine(f"sqlite:///{db_path}")
            Base.metadata.create_all(bind=engine)
            Session = sessionmaker(bind=engine)
            with Session() as db:
                db.add(
                    Federation(
                        id="fed-dr",
                        name="DR Federation",
                        status=FederationStatus.ACTIVE,
                        min_clients=2,
                        max_rounds=5,
                    )
                )
                db.add(
                    Round(
                        id="fed-dr_round1",
                        federation_id="fed-dr",
                        round_number=1,
                        status=RoundStatus.COLLECTING,
                        model_version="v1",
                    )
                )
                db.commit()
            engine.dispose()

            # This is an envelope unit/integration check, not a PostgreSQL RPO/RTO drill.
            subprocess.run(
                [
                    "python3",
                    "scripts/backup_crypto.py",
                    "encrypt",
                    str(db_path),
                    str(backup_path),
                    "--key-file",
                    str(key_file),
                    "--key-id",
                    "test-key-1",
                ],
                check=True,
            )
            digest = subprocess.check_output(["sha256sum", str(backup_path)], text=True)
            manifest_path.write_text(digest, encoding="utf-8")

            # Simulate database corruption
            db_path.write_bytes(b"CORRUPTED-STORAGE-BYTES-0000")

            subprocess.run(
                ["sha256sum", "--check", str(manifest_path)], check=True, capture_output=True
            )
            restored_path = root / "trustfl.db"
            subprocess.run(
                [
                    "python3",
                    "scripts/backup_crypto.py",
                    "decrypt",
                    str(backup_path),
                    str(restored_path),
                    "--key-file",
                    str(key_file),
                ],
                check=True,
            )

            wrong_key = root / "wrong.key"
            wrong_key.write_text("22" * 32, encoding="utf-8")
            self.assertNotEqual(
                subprocess.run(
                    [
                        "python3",
                        "scripts/backup_crypto.py",
                        "decrypt",
                        str(backup_path),
                        str(root / "wrong.db"),
                        "--key-file",
                        str(wrong_key),
                    ],
                    check=False,
                ).returncode,
                0,
            )
            tampered = bytearray(backup_path.read_bytes())
            tampered[-1] ^= 1
            backup_path.write_bytes(tampered)
            self.assertNotEqual(
                subprocess.run(
                    [
                        "python3",
                        "scripts/backup_crypto.py",
                        "decrypt",
                        str(backup_path),
                        str(root / "tampered.db"),
                        "--key-file",
                        str(key_file),
                    ],
                    check=False,
                ).returncode,
                0,
            )

            restored_engine = create_engine(f"sqlite:///{restored_path}")
            RestoredSession = sessionmaker(bind=restored_engine)
            with RestoredSession() as db:
                fed = db.get(Federation, "fed-dr")
                rnd = db.get(Round, "fed-dr_round1")
                self.assertIsNotNone(fed)
                self.assertEqual(fed.name, "DR Federation")
                self.assertIsNotNone(rnd)
                self.assertEqual(rnd.model_version, "v1")
            restored_engine.dispose()

    def test_coordinator_lease_fencing_prevents_split_brain(self) -> None:
        from apps.api.api.db.models import Base, CoordinatorLease
        from apps.coordinator.persistence import CoordinatorPersistence

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "lease.db"
            engine = create_engine(f"sqlite:///{db_path}")
            Base.metadata.create_all(bind=engine)
            Session = sessionmaker(bind=engine)

            p1 = CoordinatorPersistence.__new__(CoordinatorPersistence)
            p1.SessionLocal = Session
            p1.CoordinatorLease = CoordinatorLease
            p1.federation_id = "fed-ha"
            p1.holder_id = "coord-primary"

            p2 = CoordinatorPersistence.__new__(CoordinatorPersistence)
            p2.SessionLocal = Session
            p2.CoordinatorLease = CoordinatorLease
            p2.federation_id = "fed-ha"
            p2.holder_id = "coord-standby"

            self.assertTrue(p1.acquire_lease(ttl_seconds=2))
            self.assertFalse(p2.acquire_lease(ttl_seconds=2))

            # Release/expire primary lease -> standby takes over with incremented fencing token
            p1.release_lease()
            self.assertTrue(p2.acquire_lease(ttl_seconds=5))
            with Session() as db:
                row = db.get(CoordinatorLease, "fed-ha")
                self.assertIsNotNone(row)
                self.assertEqual(row.holder_id, "coord-standby")
                self.assertEqual(row.fencing_token, 2)
            engine.dispose()

    def test_ipfs_pinning_replication_and_failover_on_node_loss(self) -> None:
        from trustfl_storage.client import IPFSStorageClient

        srv1, h1, url1 = _start_mock_ipfs()
        srv2, h2, url2 = _start_mock_ipfs()
        try:
            client = IPFSStorageClient(api_url=url1, replica_urls=[url2], pin=True)
            payload = b"phase14-ha-model-artifact-weights"
            meta = client.save_artifact(payload, "v2", 3, client_id="c1", update_id="u3")
            cid = meta.uri.removeprefix("ipfs://")
            self.assertIn(cid, h1.pinned)
            self.assertIn(cid, h2.pinned)

            # Kill primary IPFS node -> load_artifact must fail over seamlessly to replica 2
            srv1.shutdown()
            srv1.server_close()

            recovered = client.load_artifact(meta.uri, meta.sha256_hash)
            self.assertEqual(recovered, payload)

            # Tampered replica data must still fail closed with ValueError
            h2.store[cid] = b"tampered-bytes"
            with self.assertRaises(ValueError):
                client.load_artifact(meta.uri, meta.sha256_hash)
        finally:
            try:
                srv1.shutdown()
                srv1.server_close()
            except Exception:
                pass
            srv2.shutdown()
            srv2.server_close()

    def test_blockchain_rpc_failover_and_outbox_recovery(self) -> None:
        from trustfl_blockchain.client import BlockchainClient

        from apps.coordinator.network.server import CoordinatorState

        class _RPCHandler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args) -> None:
                return

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                req = json.loads(self.rfile.read(length))
                method = req.get("method")
                result = (
                    "0x1" if method in {"eth_blockNumber", "eth_chainId", "net_version"} else True
                )
                resp = json.dumps(
                    {"jsonrpc": "2.0", "id": req.get("id", 1), "result": result}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

        rpc_srv = ThreadingHTTPServer(("127.0.0.1", 0), _RPCHandler)
        rpc_srv.daemon_threads = True
        threading.Thread(target=rpc_srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                contracts_file = Path(tmpdir) / "contracts.json"
                contracts_file.write_text(
                    json.dumps(
                        {
                            "contracts": {
                                "ClientRegistry": {
                                    "address": "0x0000000000000000000000000000000000000001",
                                    "abi": [],
                                },
                                "TrainingRoundRegistry": {
                                    "address": "0x0000000000000000000000000000000000000002",
                                    "abi": [],
                                },
                                "UpdateRegistry": {
                                    "address": "0x0000000000000000000000000000000000000003",
                                    "abi": [],
                                },
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                dead_rpc = "http://127.0.0.1:1"
                healthy_rpc = f"http://127.0.0.1:{rpc_srv.server_port}"
                dev_key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
                bc = BlockchainClient(
                    rpc_url=dead_rpc,
                    contracts_json_path=str(contracts_file),
                    private_key=dev_key,
                    fallback_rpc_urls=[healthy_rpc],
                )
                self.assertEqual(bc.rpc_url, healthy_rpc)

                # Verify coordinator outbox drains pending events on recovery
                processed: list[str] = []

                class _FakePersistence:
                    def restore_state(self):
                        return None

                    def ensure_federation(self, **_kw):
                        return None

                    def process_blockchain_outbox(self, submit_fn):
                        ok = submit_fn("ROUND_COMMIT", {"round_id": 1, "model_version": "v1"})
                        if ok:
                            processed.append("round:1:commit:v1")

                fake_bc = MagicMock()
                fake_bc.finalize_round.return_value = True
                state = CoordinatorState(
                    min_clients=1,
                    num_rounds=1,
                    persistence=_FakePersistence(),
                    blockchain_client=fake_bc,
                    require_signatures=False,
                )
                state._process_blockchain_outbox()
                self.assertEqual(processed, ["round:1:commit:v1"])
                fake_bc.finalize_round.assert_called_once_with(1, "v1")
        finally:
            rpc_srv.shutdown()
            rpc_srv.server_close()

    def test_redis_rate_limiter_runtime_fallback_and_health_gauges(self) -> None:
        import asyncio

        from trustfl_observability import metrics

        from apps.api.api.middleware.security import GlobalRateLimitMiddleware
        from apps.api.api.routers.health import _record_operational_gauges

        async def _dummy_app(_scope, _receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = GlobalRateLimitMiddleware(_dummy_app, limit="2/minute")
        failing_redis = MagicMock()
        failing_redis.incr.side_effect = ConnectionError("redis connection lost")
        mw._redis = failing_redis

        async def _call():
            statuses: list[int] = []
            for _ in range(3):
                captured: list[int] = []

                async def _recv():
                    return {"type": "http.request", "body": b""}

                async def _send(msg, out=captured):
                    if msg["type"] == "http.response.start":
                        out.append(msg["status"])

                await mw(
                    {
                        "type": "http",
                        "method": "GET",
                        "path": "/api/v1/rounds",
                        "headers": [],
                        "client": ("10.0.0.5", 1234),
                    },
                    _recv,
                    _send,
                )
                statuses.extend(captured)
            return statuses

        statuses = asyncio.run(_call())
        self.assertEqual(statuses, [200, 200, 429])

        # Verify operational secret-expiry & backup-freshness gauges
        with tempfile.TemporaryDirectory() as tmpdir:
            bfile = Path(tmpdir) / "trustfl-20261127T000000Z.dump.enc"
            bfile.write_bytes(b"enc")
            Path(f"{bfile}.sha256").write_text("digest  trustfl-20261127T000000Z.dump.enc\n")
            Path(f"{bfile}.verified").write_text("2026-11-27T00:00:00Z digest\n")
            os.environ["TLS_CERT_EXPIRY_EPOCH"] = str(int(time.time()) + 3600)
            os.environ["BACKUP_DIR"] = tmpdir
            try:
                _record_operational_gauges()
                rendered = metrics.render()
                self.assertIn("trustfl_secret_expiry_seconds", rendered)
                self.assertIn("trustfl_backup_age_seconds", rendered)
                self.assertIn("trustfl_redis_fallback_total", rendered)
            finally:
                os.environ.pop("TLS_CERT_EXPIRY_EPOCH", None)
                os.environ.pop("BACKUP_DIR", None)
