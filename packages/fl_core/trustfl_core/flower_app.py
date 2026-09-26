"""
Modern Flower Application Model abstraction & primitives.

Defines:
- FitIns, FitRes: Fit instructions and client results
- EvaluateIns, EvaluateRes: Evaluation instructions and client results
- Strategy: Server aggregation strategy (FedAvg)
- ClientApp: Flower modern client application wrapper
- ServerApp: Flower modern server application wrapper
- SimulationEngine: Multi-round local orchestration runner
"""

from __future__ import annotations
from dataclasses import dataclass, field
import random
from typing import Any, Callable, Dict, List, Optional, Tuple

from trustfl_core.model import Parameters, TinyLinearModel, generate_synthetic_data


@dataclass
class FitIns:
    """Parameters and configuration sent from server to client for training."""
    parameters: Parameters
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FitRes:
    """Updated parameters and training metrics returned from client to server."""
    parameters: Parameters
    num_examples: int
    metrics: Dict[str, Any] = field(default_factory=dict)
    status: str = "OK"


@dataclass
class EvaluateIns:
    """Parameters and configuration sent from server to client for evaluation."""
    parameters: Parameters
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluateRes:
    """Evaluation loss and metrics returned from client to server."""
    loss: float
    num_examples: int
    metrics: Dict[str, Any] = field(default_factory=dict)
    status: str = "OK"


class Strategy:
    """
    Flower Strategy Interface for orchestrating parameter aggregation and client sampling.
    """

    def initialize_parameters(self) -> Parameters:
        raise NotImplementedError

    def configure_fit(
        self,
        server_round: int,
        parameters: Parameters,
        client_manager: List[str],
    ) -> List[Tuple[str, FitIns]]:
        raise NotImplementedError

    def aggregate_fit(
        self,
        server_round: int,
        results: List[Tuple[str, FitRes]],
        failures: List[Tuple[str, BaseException]],
    ) -> Tuple[Optional[Parameters], Dict[str, Any]]:
        raise NotImplementedError

    def configure_evaluate(
        self,
        server_round: int,
        parameters: Parameters,
        client_manager: List[str],
    ) -> List[Tuple[str, EvaluateIns]]:
        raise NotImplementedError

    def aggregate_evaluate(
        self,
        server_round: int,
        results: List[Tuple[str, EvaluateRes]],
        failures: List[Tuple[str, BaseException]],
    ) -> Tuple[Optional[float], Dict[str, Any]]:
        raise NotImplementedError


class FedAvg(Strategy):
    """
    Iterative Federated Averaging (FedAvg) Strategy.
    Aggregates model parameter updates weighted by client sample sizes.
    """

    def __init__(
        self,
        fraction_fit: float = 1.0,
        fraction_evaluate: float = 1.0,
        min_fit_clients: int = 1,
        min_evaluate_clients: int = 1,
        min_available_clients: int = 1,
        initial_parameters: Optional[Parameters] = None,
        random_seed: int = 42,
    ) -> None:
        self.fraction_fit = fraction_fit
        self.fraction_evaluate = fraction_evaluate
        self.min_fit_clients = min_fit_clients
        self.min_evaluate_clients = min_evaluate_clients
        self.min_available_clients = min_available_clients
        self.initial_parameters = initial_parameters
        self.rng = random.Random(random_seed)

    def initialize_parameters(self) -> Parameters:
        if self.initial_parameters is not None:
            return self.initial_parameters
        # Default fallback initialization
        model = TinyLinearModel(in_features=4, seed=42)
        return model.get_parameters()

    def configure_fit(
        self,
        server_round: int,
        parameters: Parameters,
        client_manager: List[str],
    ) -> List[Tuple[str, FitIns]]:
        """Select clients and send fit instructions."""
        num_available = len(client_manager)
        if num_available < self.min_available_clients:
            return []

        # Determine sample size
        sample_size = max(int(num_available * self.fraction_fit), self.min_fit_clients)
        sample_size = min(sample_size, num_available)
        sampled_clients = self.rng.sample(client_manager, sample_size)

        fit_ins = FitIns(parameters=parameters, config={"server_round": server_round})
        return [(cid, fit_ins) for cid in sampled_clients]

    def aggregate_fit(
        self,
        server_round: int,
        results: List[Tuple[str, FitRes]],
        failures: List[Tuple[str, BaseException]],
    ) -> Tuple[Optional[Parameters], Dict[str, Any]]:
        """
        Computes weighted average of client parameters:
        W_global = sum(n_k * W_k) / sum(n_k)
        """
        if not results:
            return None, {"error": "No client results received for aggregation"}

        total_examples = sum(res.num_examples for _, res in results)
        if total_examples == 0:
            return None, {"error": "Total client examples is 0"}

        # First client parameters shape
        ref_params = results[0][1].parameters
        num_layers = len(ref_params)
        aggregated: Parameters = []

        for layer_idx in range(num_layers):
            layer_len = len(ref_params[layer_idx])
            acc = [0.0] * layer_len
            for _, res in results:
                weight = res.num_examples / total_examples
                client_layer = res.parameters[layer_idx]
                for i in range(layer_len):
                    acc[i] += weight * client_layer[i]
            aggregated.append(acc)

        metrics = {
            "num_successful_clients": len(results),
            "num_failed_clients": len(failures),
            "total_examples": total_examples,
        }
        return aggregated, metrics

    def configure_evaluate(
        self,
        server_round: int,
        parameters: Parameters,
        client_manager: List[str],
    ) -> List[Tuple[str, EvaluateIns]]:
        """Select clients and send evaluation instructions."""
        num_available = len(client_manager)
        if num_available < self.min_available_clients:
            return []

        sample_size = max(
            int(num_available * self.fraction_evaluate), self.min_evaluate_clients
        )
        sample_size = min(sample_size, num_available)
        sampled_clients = self.rng.sample(client_manager, sample_size)

        eval_ins = EvaluateIns(parameters=parameters, config={"server_round": server_round})
        return [(cid, eval_ins) for cid in sampled_clients]

    def aggregate_evaluate(
        self,
        server_round: int,
        results: List[Tuple[str, EvaluateRes]],
        failures: List[Tuple[str, BaseException]],
    ) -> Tuple[Optional[float], Dict[str, Any]]:
        """Computes weighted average of evaluation loss and accuracy."""
        if not results:
            return None, {}

        total_examples = sum(res.num_examples for _, res in results)
        if total_examples == 0:
            return None, {}

        weighted_loss = sum(res.loss * res.num_examples for _, res in results) / total_examples

        accuracies = [
            res.metrics["accuracy"] * res.num_examples
            for _, res in results
            if "accuracy" in res.metrics
        ]
        avg_accuracy = (
            sum(accuracies) / total_examples if accuracies else 0.0
        )

        metrics = {
            "accuracy": avg_accuracy,
            "num_eval_clients": len(results),
            "num_eval_failures": len(failures),
        }
        return weighted_loss, metrics


class FlowerClient:
    """Client interface for local training and evaluation."""

    def fit(self, ins: FitIns) -> FitRes:
        raise NotImplementedError

    def evaluate(self, ins: EvaluateIns) -> EvaluateRes:
        raise NotImplementedError


class ClientApp:
    """
    Flower ClientApp representation.
    Wraps client factory or callable to produce a client per request context.
    """

    def __init__(self, client_fn: Callable[[str], FlowerClient]) -> None:
        self.client_fn = client_fn

    def get_client(self, cid: str) -> FlowerClient:
        return self.client_fn(cid)


class ServerApp:
    """
    Flower ServerApp representation.
    Manages global rounds, strategy coordination, and parameter aggregation.
    """

    def __init__(self, strategy: Strategy, num_rounds: int = 3) -> None:
        self.strategy = strategy
        self.num_rounds = num_rounds
        self.parameters: Parameters = self.strategy.initialize_parameters()
        self.round_history: List[Dict[str, Any]] = []

    def fit_round(
        self,
        server_round: int,
        client_app: ClientApp,
        client_ids: List[str],
        failing_clients: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Executes a single federated training and evaluation round."""
        failing_clients = failing_clients or []

        # 1. Configure and sample fit
        fit_instructions = self.strategy.configure_fit(
            server_round=server_round,
            parameters=self.parameters,
            client_manager=client_ids,
        )

        results: List[Tuple[str, FitRes]] = []
        failures: List[Tuple[str, BaseException]] = []

        # 2. Local Training on Clients
        for cid, ins in fit_instructions:
            if cid in failing_clients:
                failures.append((cid, RuntimeError(f"Client {cid} simulated drop or failure")))
                continue
            try:
                client = client_app.get_client(cid)
                fit_res = client.fit(ins)
                results.append((cid, fit_res))
            except Exception as e:
                failures.append((cid, e))

        # 3. Server Aggregation
        new_params, fit_metrics = self.strategy.aggregate_fit(
            server_round=server_round,
            results=results,
            failures=failures,
        )

        if new_params is not None:
            self.parameters = new_params

        # 4. Configure and sample evaluate
        eval_instructions = self.strategy.configure_evaluate(
            server_round=server_round,
            parameters=self.parameters,
            client_manager=client_ids,
        )

        eval_results: List[Tuple[str, EvaluateRes]] = []
        eval_failures: List[Tuple[str, BaseException]] = []

        for cid, ins in eval_instructions:
            if cid in failing_clients:
                eval_failures.append((cid, RuntimeError(f"Client {cid} unavailable for eval")))
                continue
            try:
                client = client_app.get_client(cid)
                eval_res = client.evaluate(ins)
                eval_results.append((cid, eval_res))
            except Exception as e:
                eval_failures.append((cid, e))

        eval_loss, eval_metrics = self.strategy.aggregate_evaluate(
            server_round=server_round,
            results=eval_results,
            failures=eval_failures,
        )

        round_summary = {
            "round": server_round,
            "fit_metrics": fit_metrics,
            "loss": eval_loss,
            "accuracy": eval_metrics.get("accuracy", 0.0),
            "num_successful_clients": len(results),
            "num_failed_clients": len(failures),
        }
        self.round_history.append(round_summary)
        return round_summary
