"""
Unit and integration tests for TrustFL Federated Learning Core.

Proves:
1. One client works
2. Multiple clients work
3. Multiple rounds work
4. Global parameters actually change
5. Failed clients are handled safely
"""

import unittest
from apps.coordinator.coordinator import run_simulation
from trustfl_core.flower_app import FedAvg, FitRes
from trustfl_core.model import TinyLinearModel, generate_synthetic_data


class TestFederatedLearningCore(unittest.TestCase):
    def test_one_client_training(self) -> None:
        """Assert single client completes local training and evaluation."""
        sim = run_simulation(
            num_clients=1,
            num_rounds=1,
            local_epochs=2,
            random_seed=42,
        )
        self.assertEqual(sim["num_rounds_executed"], 1)
        self.assertEqual(len(sim["clients_participating"]), 1)
        self.assertEqual(sim["round_history"][0]["num_successful_clients"], 1)
        self.assertEqual(sim["round_history"][0]["num_failed_clients"], 0)

        # Accuracy should be positive
        self.assertGreater(sim["round_history"][0]["accuracy"], 0.0)

    def test_multiple_clients_training(self) -> None:
        """Assert multiple clients (e.g. 5) train and aggregate concurrently."""
        num_clients = 5
        sim = run_simulation(
            num_clients=num_clients,
            num_rounds=2,
            local_epochs=1,
            random_seed=123,
        )
        self.assertEqual(sim["num_rounds_executed"], 2)
        self.assertEqual(len(sim["clients_participating"]), num_clients)
        for round_stat in sim["round_history"]:
            self.assertEqual(round_stat["num_successful_clients"], num_clients)
            self.assertEqual(round_stat["num_failed_clients"], 0)

    def test_multiple_rounds_and_parameter_change(self) -> None:
        """Assert multi-round execution leads to parameter updates and model convergence."""
        sim = run_simulation(
            num_clients=3,
            num_rounds=4,
            local_epochs=3,
            learning_rate=0.08,
            random_seed=999,
        )
        self.assertEqual(sim["num_rounds_executed"], 4)
        initial_w = sim["initial_parameters"][0]
        final_w = sim["final_parameters"][0]

        # Verify parameters actually changed
        self.assertNotEqual(initial_w, final_w)

        # Verify difference is non-zero
        delta = sum(abs(a - b) for a, b in zip(initial_w, final_w))
        self.assertGreater(delta, 1e-4)

        # Verify loss improves or stays reasonable
        first_round_loss = sim["round_history"][0]["loss"]
        last_round_loss = sim["round_history"][-1]["loss"]
        self.assertLess(last_round_loss, first_round_loss)

    def test_failed_clients_handled_safely(self) -> None:
        """Assert server safely aggregates when some clients fail or drop out."""
        total_clients = 4
        failing = ["client_1", "client_3"]

        sim = run_simulation(
            num_clients=total_clients,
            num_rounds=2,
            local_epochs=2,
            random_seed=777,
            failing_clients=failing,
        )
        self.assertEqual(sim["num_rounds_executed"], 2)
        # 4 total clients, 2 failed => 2 successful
        for round_stat in sim["round_history"]:
            self.assertEqual(round_stat["num_successful_clients"], 2)
            self.assertEqual(round_stat["num_failed_clients"], 2)

        # Global model still updated safely by remaining clients
        initial_w = sim["initial_parameters"][0]
        final_w = sim["final_parameters"][0]
        self.assertNotEqual(initial_w, final_w)

    def test_fedavg_weighted_aggregation(self) -> None:
        """Verify mathematical correctness of sample-weighted averaging."""
        strategy = FedAvg()
        # Client A: 100 samples, w=[1.0, 1.0], b=[1.0]
        # Client B: 300 samples, w=[5.0, 5.0], b=[5.0]
        # Expected: (100*1 + 300*5)/400 = 1600/400 = 4.0
        res_a = FitRes(
            parameters=[[1.0, 1.0], [1.0]],
            num_examples=100,
        )
        res_b = FitRes(
            parameters=[[5.0, 5.0], [5.0]],
            num_examples=300,
        )
        agg_params, metrics = strategy.aggregate_fit(
            server_round=1,
            results=[("cli_a", res_a), ("cli_b", res_b)],
            failures=[],
        )
        self.assertIsNotNone(agg_params)
        self.assertAlmostEqual(agg_params[0][0], 4.0)
        self.assertAlmostEqual(agg_params[0][1], 4.0)
        self.assertAlmostEqual(agg_params[1][0], 4.0)
        self.assertEqual(metrics["num_successful_clients"], 2)
        self.assertEqual(metrics["total_examples"], 400)


if __name__ == "__main__":
    unittest.main()
