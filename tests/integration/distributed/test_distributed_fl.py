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

import os
import sys
import threading
import time
import unittest

# Make sure the coordinator network package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "apps"))

from client.network.agent import DistributedClientAgent
from coordinator.network.server import CoordinatorServer

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
            round_timeout_seconds=2.0,      # short timeout to make test fast
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
                c0.step()         # c0 trains and submits
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
                len(server.state.round_history), 1,
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
        self.assertEqual(rh2["num_successful_clients"], 2,
                         "Reconnected client should participate in round 2")

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
            min_clients=1,          # round starts when the first client registers
            num_rounds=1,
            round_timeout_seconds=1.5,
            heartbeat_timeout_seconds=30.0,
        )
        server.start()
        self.assertTrue(_wait_for_server(port))

        c0 = _make_agent("c0", port)
        c1 = _make_agent("c1", port)
        try:
            self.assertTrue(c0.register())   # triggers round 1
            self.assertTrue(c1.register())   # joins but won't submit

            # c0 submits its update; c1 never steps
            deadline = time.time() + 3.0
            while time.time() < deadline:
                c0.step()   # c0 trains and submits for round 1
                time.sleep(0.1)

            # Wait for timeout to fire and aggregate
            server.state.wait_until_done(timeout=5.0)
        finally:
            server.stop()
            c0.stop()
            c1.stop()

        self.assertEqual(len(server.state.round_history), 1,
                         "Round should have completed (via timeout)")
        rh = server.state.round_history[0]
        self.assertTrue(rh["timed_out"], "Expected timed_out=True")
        # c0 submitted; c1 never did — at least 1 successful client
        self.assertGreaterEqual(rh["num_successful_clients"], 1)


if __name__ == "__main__":
    unittest.main()
