"""Unit tests for DistributedClientAgent."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from apps.client.network.agent import DistributedClientAgent


def _synthetic_train_fn(_round_id, _params, _config):
    return [[0.1, 0.2]], 50, {"loss": 0.5}


def _make_agent(coordinator_url="http://127.0.0.1:8100"):
    return DistributedClientAgent(
        client_id="test-client",
        coordinator_url=coordinator_url,
        train_fn=_synthetic_train_fn,
        poll_interval=0.01,
        max_retries=2,
        retry_delay=0.01,
        training_timeout_seconds=1.0,
        connection_timeout_seconds=0.5,
    )


class TestDistributedClientAgent:
    def test_registration_failure_exits_loop(self):
        """If registration fails after max_retries, the agent should stop."""
        agent = _make_agent("http://unreachable:8100")

        # Mock _post to always return None (registration fails)
        with patch.object(agent, "_post", return_value=None):
            agent.start_background_loop(wait_for_registration=True)

        # Agent should have set _stop_event and not started the background thread
        assert agent._stop_event.is_set()
        assert agent._bg_thread is None or not agent._bg_thread.is_alive()

    def test_registration_retry_then_success(self):
        """Client that is cut off before registration succeeds when link returns."""
        agent = _make_agent()

        call_count = {"n": 0}

        def mock_post(path, _payload):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First attempt fails
                return None
            elif call_count["n"] == 2:
                # Second attempt succeeds
                if path == "/register":
                    return {"accepted": True}
            return None

        with patch.object(agent, "_post", side_effect=mock_post):
            agent.start_background_loop(wait_for_registration=True)

        # Should have retried and succeeded
        assert agent._registered
        assert not agent._stop_event.is_set()
        assert agent._bg_thread is not None and agent._bg_thread.is_alive()

    def test_federation_done_exits_loop(self):
        """Agent should stop when federation status is DONE."""
        agent = _make_agent()

        def mock_post(path, _payload):
            if path == "/register":
                return {"accepted": True}
            if path == "/heartbeat":
                return {}
            return None

        def mock_get(path):
            if path == "/status":
                return {"status": "DONE", "current_round": 4, "num_rounds": 3}
            if path == "/round/instructions/test-client":
                return {"is_active": False, "round_id": 3}
            return None

        with (
            patch.object(agent, "_post", side_effect=mock_post),
            patch.object(agent, "_get", side_effect=mock_get),
        ):
            agent.start_background_loop(wait_for_registration=True)

            # Wait for the background thread to run one iteration
            time.sleep(0.1)

        assert agent._stop_event.is_set()

    def test_step_submits_when_active(self):
        """When round is active, step() trains and submits."""
        agent = _make_agent()

        def mock_post(path, _payload):
            if path == "/register":
                return {"accepted": True}
            if path == "/submit":
                return {"accepted": True}
            return None

        def mock_get(path):
            if path == "/status":
                return {"status": "ROUND_ACTIVE", "current_round": 1, "num_rounds": 3}
            if path == "/round/instructions/test-client":
                return {
                    "is_active": True,
                    "round_id": 1,
                    "global_parameters": [[0.0, 0.0]],
                    "config": {"model_version": "sha256:initial", "local_epochs": 1},
                }
            if path == "/heartbeat":
                return {}
            return None

        with (
            patch.object(agent, "_post", side_effect=mock_post),
            patch.object(agent, "_get", side_effect=mock_get),
        ):
            # Register manually so the background thread doesn't interfere
            assert agent.register()
            time.sleep(0.05)

            # Run one step
            submitted = agent.step()

            assert submitted
            assert agent.last_round_submitted == 1

    def test_production_rejects_plain_http(self, monkeypatch):
        """In production environment, non-loopback plain HTTP must be rejected."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(ValueError, match="Plain HTTP"):
            DistributedClientAgent(
                client_id="prod-client",
                coordinator_url="http://remote-server.com:8100",
                train_fn=_synthetic_train_fn,
            )

    def test_production_accepts_loopback_http_and_https(self, monkeypatch):
        """In production environment, loopback HTTP and HTTPS are permitted."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        ag_loopback = DistributedClientAgent(
            client_id="prod-client-loopback",
            coordinator_url="http://127.0.0.1:8100",
            train_fn=_synthetic_train_fn,
        )
        assert ag_loopback.coordinator_url == "http://127.0.0.1:8100"

        ag_https = DistributedClientAgent(
            client_id="prod-client-https",
            coordinator_url="https://remote-server.com:8100",
            train_fn=_synthetic_train_fn,
        )
        assert ag_https.coordinator_url == "https://remote-server.com:8100"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
