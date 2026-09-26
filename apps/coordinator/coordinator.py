"""
Coordinator implementation for TrustFL.
Implements modern ServerApp, FedAvg orchestration, and simulation runner.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

from trustfl_core.flower_app import ClientApp, FedAvg, ServerApp
from trustfl_core.model import Parameters, TinyLinearModel


def create_server_app(
    num_rounds: int = 3,
    fraction_fit: float = 1.0,
    fraction_evaluate: float = 1.0,
    min_fit_clients: int = 1,
    min_evaluate_clients: int = 1,
    min_available_clients: int = 1,
    random_seed: int = 42,
    initial_parameters: Optional[Parameters] = None,
) -> ServerApp:
    """
    Factory creating a configured ServerApp with FedAvg strategy.
    """
    strategy = FedAvg(
        fraction_fit=fraction_fit,
        fraction_evaluate=fraction_evaluate,
        min_fit_clients=min_fit_clients,
        min_evaluate_clients=min_evaluate_clients,
        min_available_clients=min_available_clients,
        initial_parameters=initial_parameters,
        random_seed=random_seed,
    )
    return ServerApp(strategy=strategy, num_rounds=num_rounds)


def run_simulation(
    num_clients: int = 3,
    num_rounds: int = 3,
    local_epochs: int = 2,
    learning_rate: float = 0.05,
    client_sampling_fraction: float = 1.0,
    random_seed: int = 42,
    failing_clients: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Executes a complete federated learning simulation.

    Lifecycle:
    1. Server creates global model
    2. Loop rounds:
       a. Clients receive global parameters
       b. Clients train locally
       c. Clients evaluate
       d. Clients return parameters and metrics
       e. Server performs FedAvg
       f. Aggregated parameters become next global model
    """
    from apps.client.client import create_client_app

    client_ids = [f"client_{i}" for i in range(num_clients)]

    initial_model = TinyLinearModel(in_features=4, seed=random_seed)
    initial_params = initial_model.get_parameters()

    server_app = create_server_app(
        num_rounds=num_rounds,
        fraction_fit=client_sampling_fraction,
        fraction_evaluate=client_sampling_fraction,
        min_fit_clients=1,
        min_evaluate_clients=1,
        min_available_clients=1,
        random_seed=random_seed,
        initial_parameters=initial_params,
    )

    client_app = create_client_app(
        num_clients=num_clients,
        seed=random_seed,
        local_epochs=local_epochs,
        learning_rate=learning_rate,
    )

    history: List[Dict[str, Any]] = []

    for round_num in range(1, num_rounds + 1):
        round_res = server_app.fit_round(
            server_round=round_num,
            client_app=client_app,
            client_ids=client_ids,
            failing_clients=failing_clients,
        )
        history.append(round_res)

    final_params = server_app.parameters

    return {
        "num_rounds_executed": num_rounds,
        "clients_participating": [c for c in client_ids if c not in (failing_clients or [])],
        "all_client_ids": client_ids,
        "initial_parameters": initial_params,
        "final_parameters": final_params,
        "round_history": history,
    }
