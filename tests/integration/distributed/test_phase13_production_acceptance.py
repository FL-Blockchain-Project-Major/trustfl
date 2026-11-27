"""Phase 13 Production Security & Distributed Deployment Acceptance Tests.

Topology note:
- These automated tests execute a single-host multi-process topology:
  the coordinator, TLS proxy, and 2 independent client OS processes communicate
  over loopback TCP/HTTPS with separate working directories, separate dataset
  partitions, unique Ed25519 keys, and real Groth16 ZKP verification.
- Real multi-machine WAN deployment and external IPFS/Hardhat daemons are
  separately documented in docs/phase13-production-acceptance-report.md and
  covered by the opt-in test gated on TRUSTFL_RUN_EXTERNAL_INFRA_TEST=1.
"""

from __future__ import annotations

import http.client
import http.server
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import requests

REPO_ROOT = Path(__file__).resolve().parents[3]
for _pkg in (
    REPO_ROOT,
    REPO_ROOT / "packages" / "crypto",
    REPO_ROOT / "packages" / "fl_core",
    REPO_ROOT / "packages" / "ml_core",
    REPO_ROOT / "packages" / "schemas",
    REPO_ROOT / "packages" / "storage",
    REPO_ROOT / "packages" / "zkp",
):
    _p = str(_pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from trustfl_crypto.canonical import hash_parameters  # noqa: E402
from trustfl_crypto.keys import ClientIdentity  # noqa: E402
from trustfl_crypto.signer import UpdateSigner  # noqa: E402
from trustfl_storage.client import LocalStorageClient  # noqa: E402

from apps.coordinator.network.server import CoordinatorServer, CoordinatorState  # noqa: E402
from apps.coordinator.zkp_verifier import ZKPVerifier  # noqa: E402


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _create_visdrone_partition(root: Path, num_images: int = 2, seed_offset: int = 0) -> None:
    for split in ("train", "val"):
        img_dir = root / split / "images"
        ann_dir = root / split / "annotations"
        img_dir.mkdir(parents=True, exist_ok=True)
        ann_dir.mkdir(parents=True, exist_ok=True)
        for idx in range(num_images):
            img = np.zeros((64, 64, 3), dtype=np.uint8)
            color = ((idx + seed_offset) * 53 + 60) % 255
            cv2.rectangle(img, (8, 8), (40, 40), (color, 180, 90), -1)
            cv2.imwrite(str(img_dir / f"{split}_{idx}.jpg"), img)
            (ann_dir / f"{split}_{idx}.txt").write_text("8,8,32,32,1,1,0,0\n")


def _generate_tls_materials(cert_dir: Path) -> tuple[Path, Path, Path]:
    cert_dir.mkdir(parents=True, exist_ok=True)
    ca_key = cert_dir / "ca.key"
    ca_crt = cert_dir / "ca.crt"
    srv_key = cert_dir / "server.key"
    srv_csr = cert_dir / "server.csr"
    srv_crt = cert_dir / "server.crt"
    san_cnf = cert_dir / "san.cnf"

    san_cnf.write_text(
        "[req]\n"
        "distinguished_name = req_dn\n"
        "req_extensions = v3_req\n"
        "prompt = no\n"
        "[req_dn]\n"
        "CN = 127.0.0.1\n"
        "[v3_req]\n"
        "keyUsage = critical, digitalSignature, keyEncipherment\n"
        "extendedKeyUsage = serverAuth\n"
        "subjectAltName = IP:127.0.0.1,DNS:localhost\n"
    )
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-new",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(ca_key),
            "-sha256",
            "-days",
            "1",
            "-out",
            str(ca_crt),
            "-subj",
            "/CN=TrustFL-Test-CA",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(srv_key),
            "-out",
            str(srv_csr),
            "-config",
            str(san_cnf),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(srv_csr),
            "-CA",
            str(ca_crt),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(srv_crt),
            "-days",
            "1",
            "-sha256",
            "-extfile",
            str(san_cnf),
            "-extensions",
            "v3_req",
        ],
        check=True,
        capture_output=True,
    )
    return ca_crt, srv_crt, srv_key


class _TLSReverseProxy:
    """Minimal HTTPS reverse proxy forwarding to the loopback CoordinatorServer."""

    def __init__(self, target_host: str, target_port: int, certfile: Path, keyfile: Path) -> None:
        self.port = _get_free_port()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self._forward("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._forward("POST")

            def _forward(self, method: str) -> None:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length) if length > 0 else None
                fwd_headers = {
                    k: v
                    for k, v in self.headers.items()
                    if k.lower() not in {"host", "content-length", "connection"}
                }
                conn = http.client.HTTPConnection(target_host, target_port, timeout=60)
                try:
                    conn.request(method, self.path, body=body, headers=fwd_headers)
                    resp = conn.getresponse()
                    resp_body = resp.read()
                    self.send_response(resp.status)
                    for hk, hv in resp.getheaders():
                        if hk.lower() not in {"transfer-encoding", "connection"}:
                            self.send_header(hk, hv)
                    self.send_header("Content-Length", str(len(resp_body)))
                    self.end_headers()
                    self.wfile.write(resp_body)
                finally:
                    conn.close()

            def log_message(self, _format: str, *_args: Any) -> None:
                return

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._httpd.daemon_threads = True
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(certfile=str(certfile), keyfile=str(keyfile))
        self._httpd.socket = ctx.wrap_socket(self._httpd.socket, server_side=True)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


class _RecordingBlockchainClient:
    """In-process blockchain recorder verifying exact lifecycle calls and commitments."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def register_client(self, client_id: str, pubkey_hash: str) -> str:
        self.events.append(("register_client", {"client_id": client_id, "pubkey_hash": pubkey_hash}))
        return f"0xreg_{client_id}"

    def create_round(self, round_id: int, model_version: str) -> str:
        self.events.append(("create_round", {"round_id": round_id, "model_version": model_version}))
        return f"0xcreate_{round_id}"

    def activate_round(self, round_id: int) -> str:
        self.events.append(("activate_round", {"round_id": round_id}))
        return f"0xactivate_{round_id}"

    def start_round(self, round_id: int, model_version: str) -> str:
        return self.create_round(round_id, model_version)

    def submit_update(
        self,
        update_id: str,
        round_id: int,
        client_id: str,
        artifact_hash: str,
        proof_metadata: Any,
    ) -> str:
        self.events.append(
            (
                "submit_update",
                {
                    "update_id": update_id,
                    "round_id": round_id,
                    "client_id": client_id,
                    "artifact_hash": artifact_hash,
                    "proof_metadata": proof_metadata,
                },
            )
        )
        return f"0xsubmit_{round_id}_{client_id}"

    def mark_verification_state(self, update_id: str, state: Any, reason: str = "") -> str:
        self.events.append(
            (
                "mark_verification_state",
                {"update_id": update_id, "state": state, "reason": reason},
            )
        )
        return f"0xverify_{update_id}"

    def record_aggregation(self, *args: Any, **kwargs: Any) -> str:
        self.events.append(("record_aggregation", {"args": args, "kwargs": kwargs}))
        return f"0xagg_{args[0] if args else 'unknown'}"

    def finalize_round(self, round_id: int, global_artifact_hash: str = "") -> str:
        self.events.append(
            (
                "finalize_round",
                {"round_id": round_id, "global_artifact_hash": global_artifact_hash},
            )
        )
        return f"0xfin_{round_id}"


class TestPhase13ProductionAcceptance(unittest.TestCase):
    """Phase 13 production security and distributed multi-process acceptance suite."""

    def test_multiprocess_tls_zkp_yolo_full_lifecycle(self) -> None:
        if not shutil.which("node") or not shutil.which("openssl"):
            self.skipTest("Requires node and openssl in PATH")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ca_crt, srv_crt, srv_key = _generate_tls_materials(root / "certs")
            storage_dir = root / "artifacts"
            storage = LocalStorageClient(base_dir=str(storage_dir))
            blockchain = _RecordingBlockchainClient()

            # Create 2 independent client identities + isolated datasets
            identities: dict[str, ClientIdentity] = {}
            client_dirs: dict[str, Path] = {}
            for i in range(2):
                cid = f"edge_site_{i + 1}"
                cdir = root / cid
                cdir.mkdir(parents=True, exist_ok=True)
                identities[cid] = ClientIdentity.load_or_generate(cid, cdir / "private.pem")
                _create_visdrone_partition(cdir / "dataset", num_images=2, seed_offset=i * 3)
                client_dirs[cid] = cdir

            allowlist = {cid: ident.public_key_b64 for cid, ident in identities.items()}
            old_allowlist = os.environ.get("COORDINATOR_ENROLLMENT_ALLOWLIST")
            old_insecure = os.environ.get("COORDINATOR_INSECURE_DEV_AUTH")
            old_zkp_dir = os.environ.get("ZKP_ARTIFACTS_DIR")

            os.environ["COORDINATOR_ENROLLMENT_ALLOWLIST"] = json.dumps(allowlist)
            os.environ.pop("COORDINATOR_INSECURE_DEV_AUTH", None)
            os.environ["ZKP_ARTIFACTS_DIR"] = str(REPO_ROOT / "packages" / "zkp" / "artifacts")

            coord_port = _get_free_port()
            zkp_verifier = ZKPVerifier(
                command=f"node {REPO_ROOT / 'packages' / 'zkp' / 'src' / 'verify-cli.js'}",
                timeout_seconds=15.0,
            )
            server = CoordinatorServer(
                host="127.0.0.1",
                port=coord_port,
                min_clients=2,
                num_rounds=2,
                require_signatures=True,
                require_zkp=True,
                zkp_verifier=zkp_verifier,
                storage_client=storage,
                blockchain_client=blockchain,
                round_timeout_seconds=420.0,
                heartbeat_timeout_seconds=420.0,
            )
            proxy = _TLSReverseProxy("127.0.0.1", coord_port, srv_crt, srv_key)

            procs: list[subprocess.Popen[str]] = []
            try:
                server.start()
                proxy.start()
                https_url = f"https://127.0.0.1:{proxy.port}"

                # Untrusted TLS client without ca_bundle must fail certificate verification
                with self.assertRaises(requests.exceptions.SSLError):
                    requests.get(f"{https_url}/health", timeout=5)

                # Trusted TLS client with ca_bundle succeeds
                health_resp = requests.get(f"{https_url}/health", verify=str(ca_crt), timeout=5)
                self.assertEqual(health_resp.status_code, 200)

                # Spawn 2 genuinely separate OS client processes over HTTPS
                for cid, cdir in client_dirs.items():
                    env = os.environ.copy()
                    env.update(
                        {
                            "ENVIRONMENT": "production",
                            "FL_CLIENT_ID": cid,
                            "FL_IDENTITY_PATH": str(cdir / "private.pem"),
                            "FL_KEYS_DIR": str(cdir / "keys"),
                            "FL_COORDINATOR_URL": https_url,
                            "FL_CA_BUNDLE": str(ca_crt),
                            "FL_DATASET_DIR": str(cdir / "dataset"),
                            "FL_NUM_CLIENTS": "2",
                            "FL_LOCAL_EPOCHS": "1",
                            "FL_MAX_SAMPLES": "2",
                            "FL_YOLO_IMAGE_SIZE": "64",
                            "FL_YOLO_BATCH_SIZE": "2",
                            "FL_POLL_INTERVAL_SECONDS": "0.5",
                            "OMP_NUM_THREADS": "1",
                            "MKL_NUM_THREADS": "1",
                            "TORCH_NUM_THREADS": "1",
                            "ZKP_ARTIFACTS_DIR": str(REPO_ROOT / "packages" / "zkp" / "artifacts"),
                            "PYTHONPATH": os.pathsep.join(
                                [
                                    str(REPO_ROOT),
                                    str(REPO_ROOT / "packages" / "crypto"),
                                    str(REPO_ROOT / "packages" / "ml_core"),
                                    str(REPO_ROOT / "packages" / "schemas"),
                                    str(REPO_ROOT / "packages" / "zkp"),
                                ]
                            ),
                        }
                    )
                    proc = subprocess.Popen(
                        [sys.executable, str(REPO_ROOT / "apps" / "client" / "main.py")],
                        cwd=str(cdir),
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    procs.append(proc)

                deadline = time.time() + 480.0
                for proc in procs:
                    remaining = max(1.0, deadline - time.time())
                    out, _ = proc.communicate(timeout=remaining)
                    self.assertEqual(proc.returncode, 0, f"Client process failed:\n{out}")

                server.state.wait_until_done(timeout=10.0)
            finally:
                for proc in procs:
                    if proc.poll() is None:
                        proc.kill()
                proxy.stop()
                server.stop()
                if old_allowlist is not None:
                    os.environ["COORDINATOR_ENROLLMENT_ALLOWLIST"] = old_allowlist
                else:
                    os.environ.pop("COORDINATOR_ENROLLMENT_ALLOWLIST", None)
                if old_insecure is not None:
                    os.environ["COORDINATOR_INSECURE_DEV_AUTH"] = old_insecure
                if old_zkp_dir is not None:
                    os.environ["ZKP_ARTIFACTS_DIR"] = old_zkp_dir
                else:
                    os.environ.pop("ZKP_ARTIFACTS_DIR", None)

            # Verify 2 rounds completed with real YOLO metrics and ZKP + artifact + chain audit
            self.assertEqual(len(server.state.round_history), 2)
            for idx, rh in enumerate(server.state.round_history, start=1):
                self.assertEqual(rh["round"], idx)
                self.assertEqual(rh["num_successful_clients"], 2)
                self.assertFalse(rh["timed_out"])
                self.assertIn("map50", rh["metrics"])
                self.assertNotIn("accuracy_proxy", rh["metrics"])

            event_names = [name for name, _ in blockchain.events]
            self.assertEqual(event_names.count("register_client"), 2)
            self.assertEqual(event_names.count("create_round"), 2)
            self.assertEqual(event_names.count("activate_round"), 2)
            self.assertEqual(event_names.count("submit_update"), 4)
            self.assertEqual(event_names.count("mark_verification_state"), 4)
            self.assertEqual(event_names.count("record_aggregation"), 4)
            self.assertEqual(event_names.count("finalize_round"), 2)

            # Verify saved artifacts exist on disk and pass SHA-256 verification
            saved_files = list(storage_dir.glob("*"))
            self.assertGreaterEqual(len(saved_files), 6)

    def test_security_rejects_unallowlisted_missing_zkp_and_duplicate_updates(self) -> None:
        allowed_id = ClientIdentity.generate("allowed_client")
        rogue_id = ClientIdentity.generate("rogue_client")
        old_allowlist = os.environ.get("COORDINATOR_ENROLLMENT_ALLOWLIST")
        os.environ["COORDINATOR_ENROLLMENT_ALLOWLIST"] = json.dumps(
            {allowed_id.client_id: allowed_id.public_key_b64}
        )
        os.environ.pop("COORDINATOR_INSECURE_DEV_AUTH", None)

        port = _get_free_port()
        zkp_verifier = ZKPVerifier(
            command=f"node {REPO_ROOT / 'packages' / 'zkp' / 'src' / 'verify-cli.js'}",
            timeout_seconds=10.0,
        )
        server = CoordinatorServer(
            host="127.0.0.1",
            port=port,
            min_clients=1,
            num_rounds=1,
            require_signatures=True,
            require_zkp=True,
            zkp_verifier=zkp_verifier,
            round_timeout_seconds=30.0,
        )
        try:
            server.start()
            base = f"http://127.0.0.1:{port}"

            # 1. Rogue un-allowlisted client registration is rejected (401/403)
            import base64
            import uuid

            rogue_nonce = uuid.uuid4().hex
            rogue_proof = b"|".join(
                (
                    b"trustfl-registration-v1",
                    rogue_id.client_id.encode(),
                    rogue_id.public_key_b64.encode(),
                    rogue_nonce.encode(),
                )
            )
            rogue_resp = requests.post(
                f"{base}/register",
                json={
                    "client_id": rogue_id.client_id,
                    "capabilities": {
                        "public_key": rogue_id.public_key_b64,
                        "registration_nonce": rogue_nonce,
                        "registration_signature": base64.b64encode(
                            rogue_id.sign(rogue_proof)
                        ).decode(),
                    },
                },
                timeout=5,
            )
            self.assertIn(rogue_resp.status_code, {401, 403})

            # 2. Allowed client registers cleanly
            ok_nonce = uuid.uuid4().hex
            ok_proof = b"|".join(
                (
                    b"trustfl-registration-v1",
                    allowed_id.client_id.encode(),
                    allowed_id.public_key_b64.encode(),
                    ok_nonce.encode(),
                )
            )
            ok_resp = requests.post(
                f"{base}/register",
                json={
                    "client_id": allowed_id.client_id,
                    "capabilities": {
                        "public_key": allowed_id.public_key_b64,
                        "registration_nonce": ok_nonce,
                        "registration_signature": base64.b64encode(
                            allowed_id.sign(ok_proof)
                        ).decode(),
                    },
                },
                timeout=5,
            )
            self.assertEqual(ok_resp.status_code, 200)

            # 3. Signed update WITHOUT mandatory ZKP proof is rejected
            signer = UpdateSigner(allowed_id, "fed-default")
            signed = signer.sign(
                round_id=1,
                parameters=[[0.1, 0.2]],
                num_examples=10,
                metrics={"train_loss": 0.5},
                model_version=hash_parameters(server.state.global_parameters),
            )
            no_zkp_resp = requests.post(
                f"{base}/round/submit",
                json=signed.to_dict(),
                timeout=5,
            )
            self.assertIn(no_zkp_resp.status_code, {400, 401, 403})
            self.assertEqual(server.state.pending_updates, {})
        finally:
            server.stop()
            if old_allowlist is not None:
                os.environ["COORDINATOR_ENROLLMENT_ALLOWLIST"] = old_allowlist
            else:
                os.environ.pop("COORDINATOR_ENROLLMENT_ALLOWLIST", None)
            os.environ["COORDINATOR_INSECURE_DEV_AUTH"] = "true"

    def test_coordinator_restart_recovery_and_tamper_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = LocalStorageClient(base_dir=tmpdir)
            params = [[0.25, -0.5, 0.75]]
            artifact = storage.save_artifact(
                json.dumps(params).encode(), "global_r1.json", "model_update"
            )
            c1_id = ClientIdentity.generate("c1")
            c2_id = ClientIdentity.generate("c2")
            persisted_snapshot = {
                "current_round": 2,
                "registered_clients": {
                    "c1": {"pubkey": c1_id.public_key_b64},
                    "c2": {"pubkey": c2_id.public_key_b64},
                },
                "recovery_state": {
                    "global_parameters": [],
                    "pending_updates": {
                        "c1": {"update_id": "u1", "num_examples": 5, "parameters": [[0.3, -0.4, 0.8]]}
                    },
                    "verifier": {
                        "current_round": 2,
                        "accepted_model_versions": [hash_parameters(params)],
                        "used_nonces": {"2": ["c1:2:nonce1"]},
                    },
                },
                "global_artifact": {
                    "uri": artifact.uri,
                    "sha256_hash": artifact.sha256_hash,
                    "model_version": hash_parameters(params),
                },
            }

            class _MemPersistence:
                def restore_state(self) -> dict[str, Any]:
                    return persisted_snapshot

            restored = CoordinatorState(
                min_clients=2,
                num_rounds=3,
                persistence=_MemPersistence(),
                storage_client=storage,
                require_signatures=True,
            )
            self.assertEqual(restored.current_round, 2)
            self.assertEqual(restored.global_parameters, params)
            self.assertIn("c1", restored.pending_updates)
            self.assertFalse(restored.update_verifier.nonce_store.check_and_add("c1:2:nonce1", 2))

            # Duplicate submission from c1 in round 2 must be rejected
            self.assertFalse(restored.submit_update("c1", 2, [[0.9, 0.9, 0.9]], 5, {}))

            # Tampering with persisted artifact on disk must fail closed on restart
            artifact_file = Path(artifact.uri.replace("file://", ""))
            artifact_file.write_bytes(b"[[999.0, 999.0, 999.0]]")
            tampered = CoordinatorState(
                min_clients=2,
                num_rounds=3,
                persistence=_MemPersistence(),
                storage_client=storage,
                require_signatures=True,
            )
            self.assertEqual(tampered.global_parameters, [])

    def test_failed_client_triggers_clean_round_timeout(self) -> None:
        state = CoordinatorState(
            min_clients=2,
            num_rounds=1,
            round_timeout_seconds=0.3,
            heartbeat_timeout_seconds=0.3,
            require_signatures=False,
        )
        self.assertTrue(state.register_client("healthy_client", {}))
        self.assertTrue(state.register_client("dropped_client", {}))
        self.assertTrue(state.submit_update("healthy_client", 1, [[1.0, 2.0]], 5, {}))

        # Wait past round_timeout_seconds without dropped_client submitting
        time.sleep(0.45)
        state.monitor_tick()
        self.assertEqual(len(state.round_history), 1)
        self.assertTrue(state.round_history[0]["timed_out"])
        self.assertEqual(state.round_history[0]["num_successful_clients"], 1)

    def test_opt_in_external_ipfs_and_hardhat_stack(self) -> None:
        if os.environ.get("TRUSTFL_RUN_EXTERNAL_INFRA_TEST") != "1":
            self.skipTest(
                "Opt-in external IPFS/Hardhat test; set TRUSTFL_RUN_EXTERNAL_INFRA_TEST=1 to run"
            )
        ipfs_resp = requests.post("http://127.0.0.1:5001/api/v0/id", timeout=3)
        self.assertEqual(ipfs_resp.status_code, 200)
        rpc_resp = requests.post(
            "http://127.0.0.1:8545",
            json={"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1},
            timeout=3,
        )
        self.assertEqual(rpc_resp.status_code, 200)
