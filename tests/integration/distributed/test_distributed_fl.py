"""
Integration tests for distributed TrustFL (Stage 04).

Tests spin up real CoordinatorServer instances on localhost using
ephemeral ports.  All HTTP communication is real — no mocks.

test_01  coordinator + 2 clients, 1 round  — happy path
test_02  coordinator + 3 clients, 2 rounds — multi-round
test_03  one client fails (never submits)  — timeout aggregation
test_04  client reconnect                  — re-registration
test_05  round timeout with partial update — timed_out flag
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path

# Make sure the coordinator network package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "apps"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "packages", "crypto"))

from client.network.agent import DistributedClientAgent
from coordinator.network.server import CoordinatorServer
from trustfl_crypto.keys import ClientIdentity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NEXT_PORT = 8200  # bump per test so ports don't collide
_PORT_LOCK = threading.Lock()


def _get_port() -> int:
    global _NEXT_PORT
    with _PORT_LOCK:
        p = _NEXT_PORT
        _NEXT_PORT += 1
    return p


def _dummy_train(round_id, global_params, _config):
    """Instant deterministic training fn — returns perturbed params."""
    if global_params:
        updated = [[v + 0.01 * round_id for v in layer] for layer in global_params]
    else:
        updated = [[float(round_id)] * 5]
    return updated, 10, {"loss": 0.5 / round_id if round_id else 0.5}


def _make_agent(client_id: str, port: int, **kwargs) -> DistributedClientAgent:
    return DistributedClientAgent(
        client_id=client_id,
        coordinator_url=f"http://127.0.0.1:{port}",
        train_fn=_dummy_train,
        poll_interval=0.2,
        max_retries=3,
        retry_delay=0.1,
        connection_timeout_seconds=3.0,
        **kwargs,
    )


def _wait_for_server(port: int, timeout: float = 5.0) -> bool:
    """Block until the server is accepting connections."""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.05)
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDistributedFL(unittest.TestCase):
    def setUp(self):
        self._old_insecure = os.environ.get("COORDINATOR_INSECURE_DEV_AUTH")
        os.environ["COORDINATOR_INSECURE_DEV_AUTH"] = "true"

    def tearDown(self):
        if self._old_insecure is None:
            os.environ.pop("COORDINATOR_INSECURE_DEV_AUTH", None)
        else:
            os.environ["COORDINATOR_INSECURE_DEV_AUTH"] = self._old_insecure

    # ── test_01: 2 clients, 1 round ─────────────────────────────────────────

    def test_01_two_clients_one_round(self):
        port = _get_port()
        server = CoordinatorServer(
            host="127.0.0.1",
            port=port,
            min_clients=2,
            num_rounds=1,
            round_timeout_seconds=15.0,
            heartbeat_timeout_seconds=30.0,
        )
        server.start()
        self.assertTrue(_wait_for_server(port), "Server did not start in time")

        agents = [_make_agent(f"c{i}", port) for i in range(2)]
        try:
            for ag in agents:
                self.assertTrue(ag.register(), f"{ag.client_id} registration failed")

            # Poll manually until done or timeout
            deadline = time.time() + 10.0
            while time.time() < deadline and server.state.current_round <= server.state.num_rounds:
                for ag in agents:
                    ag.step()
                time.sleep(0.1)

            server.state.wait_until_done(timeout=5.0)
        finally:
            server.stop()
            for ag in agents:
                ag.stop()

        self.assertEqual(len(server.state.round_history), 1, "Expected 1 completed round")
        rh = server.state.round_history[0]
        self.assertEqual(rh["round"], 1)
        self.assertEqual(rh["num_successful_clients"], 2)
        self.assertFalse(rh["timed_out"])

    def test_01b_signed_client_lifecycle(self):
        """A real client identity can register and submit an accepted update."""
        port = _get_port()
        server = CoordinatorServer(
            host="127.0.0.1",
            port=port,
            min_clients=1,
            num_rounds=1,
            require_signatures=True,
            round_timeout_seconds=15.0,
            heartbeat_timeout_seconds=30.0,
        )
        server.start()
        self.assertTrue(_wait_for_server(port))
        agent = _make_agent("signed-client", port)
        try:
            self.assertTrue(agent.register())
            deadline = time.time() + 10.0
            while time.time() < deadline and not server.state.round_history:
                agent.step()
                time.sleep(0.1)
            server.state.wait_until_done(timeout=5.0)
        finally:
            server.stop()
            agent.stop()

        self.assertEqual(len(server.state.round_history), 1)
        self.assertEqual(server.state.round_history[0]["num_successful_clients"], 1)

    # ── test_02: 3 clients, 2 rounds ────────────────────────────────────────

    def test_02_three_clients_two_rounds(self):
        port = _get_port()
        server = CoordinatorServer(
            host="127.0.0.1",
            port=port,
            min_clients=3,
            num_rounds=2,
            round_timeout_seconds=15.0,
            heartbeat_timeout_seconds=30.0,
        )
        server.start()
        self.assertTrue(_wait_for_server(port))

        agents = [_make_agent(f"c{i}", port) for i in range(3)]
        try:
            for ag in agents:
                self.assertTrue(ag.register())

            deadline = time.time() + 15.0
            while time.time() < deadline and server.state.current_round <= server.state.num_rounds:
                for ag in agents:
                    ag.step()
                time.sleep(0.1)

            server.state.wait_until_done(timeout=5.0)
        finally:
            server.stop()
            for ag in agents:
                ag.stop()

        self.assertEqual(len(server.state.round_history), 2)
        for i, rh in enumerate(server.state.round_history, start=1):
            self.assertEqual(rh["round"], i)
            self.assertEqual(rh["num_successful_clients"], 3)
            self.assertFalse(rh["timed_out"])

    # ── test_03: one client fails (never submits) — timeout handles it ──────

    def test_03_one_client_fails(self):
        port = _get_port()
        server = CoordinatorServer(
            host="127.0.0.1",
            port=port,
            min_clients=2,
            num_rounds=1,
            round_timeout_seconds=2.0,  # short timeout to make test fast
            heartbeat_timeout_seconds=30.0,
        )
        server.start()
        self.assertTrue(_wait_for_server(port))

        # c0 trains normally; c1 registers but never submits
        c0 = _make_agent("c0", port)
        c1 = _make_agent("c1", port)
        try:
            self.assertTrue(c0.register())
            self.assertTrue(c1.register())

            deadline = time.time() + 6.0
            while time.time() < deadline and server.state.current_round <= server.state.num_rounds:
                c0.step()  # c0 trains and submits
                # c1 deliberately does NOT step (simulates crash)
                time.sleep(0.2)

            server.state.wait_until_done(timeout=5.0)
        finally:
            server.stop()
            c0.stop()
            c1.stop()

        self.assertEqual(len(server.state.round_history), 1)
        rh = server.state.round_history[0]
        # c0 submitted; c1 did not → timed_out
        self.assertTrue(rh["timed_out"], "Expected timed_out=True when c1 never submitted")
        self.assertEqual(rh["num_successful_clients"], 1)

    # ── test_04: client reconnect ────────────────────────────────────────────

    def test_04_client_reconnect(self):
        """
        Round 1: c0 + c1 participate.
        Between rounds c1 'disconnects' (stop) and 're-connects' (new agent, same id).
        Round 2: c0 + c1_reconnected both participate.
        """
        port = _get_port()
        server = CoordinatorServer(
            host="127.0.0.1",
            port=port,
            min_clients=2,
            num_rounds=2,
            round_timeout_seconds=10.0,
            heartbeat_timeout_seconds=30.0,
        )
        server.start()
        self.assertTrue(_wait_for_server(port))

        c0 = _make_agent("c0", port)
        c1 = _make_agent("c1", port)
        try:
            self.assertTrue(c0.register())
            self.assertTrue(c1.register())

            # Drive round 1
            deadline = time.time() + 8.0
            while time.time() < deadline and server.state.current_round <= 1:
                c0.step()
                c1.step()
                time.sleep(0.1)

            self.assertEqual(
                len(server.state.round_history),
                1,
                "Round 1 should be done before reconnect test",
            )

            # c1 disconnects (simulate by stopping it and creating a fresh agent)
            c1.stop()
            c1_reconnected = _make_agent("c1", port)
            self.assertTrue(c1_reconnected.register(), "Reconnect registration failed")

            # Drive round 2
            deadline = time.time() + 8.0
            while time.time() < deadline and server.state.current_round <= server.state.num_rounds:
                c0.step()
                c1_reconnected.step()
                time.sleep(0.1)

            server.state.wait_until_done(timeout=5.0)
        finally:
            server.stop()
            c0.stop()
            try:
                c1_reconnected.stop()  # type: ignore[possibly-undefined]
            except Exception:
                pass

        self.assertEqual(len(server.state.round_history), 2)
        rh2 = server.state.round_history[1]
        self.assertEqual(rh2["round"], 2)
        self.assertEqual(
            rh2["num_successful_clients"], 2, "Reconnected client should participate in round 2"
        )

    # ── test_05: round timeout — partial submission, timed_out=True ─────────

    def test_05_round_timeout(self):
        """
        min_clients=1 so the round starts immediately when c0 registers.
        c0 submits; c1 registers but never submits.
        The short round_timeout fires and aggregates with only c0's update.
        """
        port = _get_port()
        server = CoordinatorServer(
            host="127.0.0.1",
            port=port,
            min_clients=1,  # round starts when the first client registers
            num_rounds=1,
            round_timeout_seconds=1.5,
            heartbeat_timeout_seconds=30.0,
        )
        server.start()
        self.assertTrue(_wait_for_server(port))

        c0 = _make_agent("c0", port)
        c1 = _make_agent("c1", port)
        try:
            self.assertTrue(c0.register())  # triggers round 1
            self.assertTrue(c1.register())  # joins but won't submit

            # c0 submits its update; c1 never steps
            deadline = time.time() + 3.0
            while time.time() < deadline:
                c0.step()  # c0 trains and submits for round 1
                time.sleep(0.1)

            # Wait for timeout to fire and aggregate
            server.state.wait_until_done(timeout=5.0)
        finally:
            server.stop()
            c0.stop()
            c1.stop()

        self.assertEqual(
            len(server.state.round_history), 1, "Round should have completed (via timeout)"
        )
        rh = server.state.round_history[0]
        self.assertTrue(rh["timed_out"], "Expected timed_out=True")
        # c0 submitted; c1 never did — at least 1 successful client
        self.assertGreaterEqual(rh["num_successful_clients"], 1)

    # ── test_06: 3 clients, 1 killed mid-run loses quorum and aborts ─────────

    def test_06_three_clients_one_killed_mid_run(self):
        """
        min_clients=3. Round 1 completes with 3 clients.
        In round 2, c2 is killed/stopped mid-run and heartbeat times out.
        Server detects active_clients < min_clients, marks round as FAILED,
        and aborts federation cleanly.
        """
        port = _get_port()
        server = CoordinatorServer(
            host="127.0.0.1",
            port=port,
            min_clients=3,
            num_rounds=2,
            round_timeout_seconds=2.0,
            heartbeat_timeout_seconds=1.0,  # fast heartbeat timeout for testing
        )
        server.start()
        self.assertTrue(_wait_for_server(port))

        agents = [_make_agent(f"c{i}", port) for i in range(3)]
        try:
            for ag in agents:
                self.assertTrue(ag.register())

            # Round 1 completes
            deadline = time.time() + 6.0
            while time.time() < deadline and server.state.current_round <= 1:
                for ag in agents:
                    ag.step()
                time.sleep(0.1)

            self.assertEqual(len(server.state.round_history), 1)

            # Round 2: kill c2
            agents[2].stop()

            # Step c0 and c1 so they submit round 2 updates
            deadline = time.time() + 6.0
            while time.time() < deadline and not server.state.aborted:
                agents[0].step()
                agents[1].step()
                time.sleep(0.1)

            self.assertTrue(server.state.aborted, "Server state should be aborted")
            self.assertEqual(server.state.get_status()["status"], "ABORTED")
            self.assertEqual(len(server.state.round_history), 2)
            self.assertEqual(server.state.round_history[-1]["status"], "FAILED")
        finally:
            server.stop()
            for ag in agents:
                try:
                    ag.stop()
                except Exception:
                    pass

    # ── test_07: 3 clients, 3 rounds, signatures on, allowlist on, real data ──

    def test_07_three_clients_three_rounds_signatures_allowlist_real_data(self):
        """
        End-to-end integration test:
        - 3 clients over 3 rounds
        - require_signatures = True
        - Allowlist enabled via COORDINATOR_ENROLLMENT_ALLOWLIST
        - Real VisDrone dataset partitioned with partition_dataset (seed & Dirichlet)
        - Trained via SimulatedDetector directly (validates real train/eval cycle)
        """
        import tempfile

        from PIL import Image
        from trustfl_ml.config import TrainingConfig
        from trustfl_ml.yolo_wrapper import SimulatedDetector

        from datasets.tools.visdrone_prep.prepare import partition_dataset

        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        raw_images = repo_root / "datasets" / "raw" / "visdrone" / "images"
        raw_annotations = repo_root / "datasets" / "raw" / "visdrone" / "annotations"

        with tempfile.TemporaryDirectory() as tmpdir:
            if not (raw_images.is_dir() and any(raw_images.iterdir())):
                # When raw datasets are not checked into Git (e.g., CI runners),
                # synthesize valid VisDrone images and annotations for the test.
                raw_images = Path(tmpdir) / "source_visdrone" / "images"
                raw_annotations = Path(tmpdir) / "source_visdrone" / "annotations"
                raw_images.mkdir(parents=True, exist_ok=True)
                raw_annotations.mkdir(parents=True, exist_ok=True)
                for idx in range(15):
                    im_path = raw_images / f"sample_{idx:03d}.jpg"
                    im = Image.new("RGB", (640, 480), color=(idx * 16 % 255, 120, 140))
                    im.save(im_path)
                    ann_path = raw_annotations / f"sample_{idx:03d}.txt"
                    ann_path.write_text(
                        "50,50,100,80,1,1,0,0\n160,120,60,60,1,4,0,0\n240,200,80,50,1,5,0,0\n",
                        encoding="utf-8",
                    )

            out_partitions = Path(tmpdir) / "partitions"
            manifest = partition_dataset(
                images_dir=raw_images,
                annotations_dir=raw_annotations,
                output_dir=out_partitions,
                num_clients=3,
                samples_per_client=5,
                seed=42,
                dirichlet=True,
                alpha=0.5,
            )

            def _make_train_fn(
                train_imgs_dir: str,
                train_ann_dir: str,
                val_imgs_dir: str,
                val_ann_dir: str,
            ):
                """Build a real train callable using SimulatedDetector on actual VisDrone data."""

                def train_fn(_round_id: int, global_params, _config):
                    model = SimulatedDetector()
                    if global_params:
                        model.set_parameters(global_params)
                    train_cfg = TrainingConfig(epochs=1)
                    train_metrics = model.train_on_dataset(
                        images_dir=train_imgs_dir,
                        annotations_dir=train_ann_dir,
                        config=train_cfg,
                        max_samples=10,
                    )
                    # Use actual samples trained, not max_samples
                    num_examples = max(1, train_metrics["samples_trained"])
                    # Evaluate on val split (not train)
                    eval_metrics = model.evaluate_on_dataset(
                        images_dir=val_imgs_dir,
                        annotations_dir=val_ann_dir,
                        max_samples=5,
                    )
                    # Only pass numeric metrics to coordinator
                    numeric_metrics = {
                        k: float(v) for k, v in eval_metrics.items() if isinstance(v, (int, float))
                    }
                    return model.get_parameters(), num_examples, numeric_metrics

                return train_fn

            # Generate identities for 3 clients
            identities = {f"client_{i}": ClientIdentity.generate(f"client_{i}") for i in range(3)}
            allowlist = {cid: ident.public_key_b64 for cid, ident in identities.items()}

            old_allowlist = os.environ.get("COORDINATOR_ENROLLMENT_ALLOWLIST")
            os.environ["COORDINATOR_ENROLLMENT_ALLOWLIST"] = json.dumps(allowlist)
            # Disable insecure dev auth so enrollment strictly enforces signature and allowlist
            os.environ.pop("COORDINATOR_INSECURE_DEV_AUTH", None)

            port = _get_port()
            server = CoordinatorServer(
                host="127.0.0.1",
                port=port,
                min_clients=3,
                num_rounds=3,
                require_signatures=True,
                round_timeout_seconds=20.0,
                heartbeat_timeout_seconds=30.0,
            )
            server.start()
            self.assertTrue(_wait_for_server(port))

            agents = []
            try:
                for i in range(3):
                    cid = f"client_{i}"
                    c_info = manifest["clients"][cid]
                    train_fn = _make_train_fn(
                        train_imgs_dir=c_info["train_images_dir"],
                        train_ann_dir=c_info["train_annotations_dir"],
                        val_imgs_dir=c_info["val_images_dir"],
                        val_ann_dir=c_info["val_annotations_dir"],
                    )
                    ag = DistributedClientAgent(
                        client_id=cid,
                        coordinator_url=f"http://127.0.0.1:{port}",
                        identity=identities[cid],
                        train_fn=train_fn,
                        poll_interval=0.1,
                        max_retries=3,
                        retry_delay=0.1,
                        connection_timeout_seconds=5.0,
                    )
                    agents.append(ag)

                for ag in agents:
                    self.assertTrue(ag.register(), f"Registration failed for {ag.client_id}")

                deadline = time.time() + 30.0
                while (
                    time.time() < deadline and server.state.current_round <= server.state.num_rounds
                ):
                    for ag in agents:
                        ag.step()
                    time.sleep(0.05)

                server.state.wait_until_done(timeout=5.0)
            finally:
                if old_allowlist is not None:
                    os.environ["COORDINATOR_ENROLLMENT_ALLOWLIST"] = old_allowlist
                else:
                    os.environ.pop("COORDINATOR_ENROLLMENT_ALLOWLIST", None)
                os.environ["COORDINATOR_INSECURE_DEV_AUTH"] = "true"
                server.stop()
                for ag in agents:
                    try:
                        ag.stop()
                    except Exception:
                        pass

            self.assertEqual(len(server.state.round_history), 3)
            for r_idx, rh in enumerate(server.state.round_history, start=1):
                self.assertEqual(rh["round"], r_idx)
                self.assertEqual(rh["num_successful_clients"], 3)
                self.assertFalse(rh["timed_out"])
                self.assertIn("accuracy_proxy", rh["metrics"])


if __name__ == "__main__":
    unittest.main()
