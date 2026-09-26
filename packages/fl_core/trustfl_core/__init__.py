"""
TrustFL Core Federated Learning Package.
"""

from trustfl_core.flower_app import (
    ClientApp,
    EvaluateIns,
    EvaluateRes,
    FedAvg,
    FitIns,
    FitRes,
    FlowerClient,
    ServerApp,
    Strategy,
)
from trustfl_core.model import Parameters, TinyLinearModel, generate_synthetic_data

__all__ = [
    "Parameters",
    "TinyLinearModel",
    "generate_synthetic_data",
    "FitIns",
    "FitRes",
    "EvaluateIns",
    "EvaluateRes",
    "Strategy",
    "FedAvg",
    "FlowerClient",
    "ClientApp",
    "ServerApp",
]
