"""
Client implementation for TrustFL.
Implements modern FlowerClient with local dataset partition and gradient descent.
"""

from __future__ import annotations

from trustfl_core.flower_app import EvaluateIns, EvaluateRes, FitIns, FitRes, FlowerClient
from trustfl_core.model import TinyLinearModel, generate_synthetic_data


class TrustFLClient(FlowerClient):
    """
    Edge client training on local partition of data.
    """

    def __init__(
        self,
        cid: str,
        train_data: tuple[list[list[float]], list[float]],
        test_data: tuple[list[list[float]], list[float]],
        local_epochs: int = 2,
        learning_rate: float = 0.05,
    ) -> None:
        self.cid = cid
        self.train_x, self.train_y = train_data
        self.test_x, self.test_y = test_data
        self.local_epochs = local_epochs
        self.learning_rate = learning_rate
        self.model = TinyLinearModel(in_features=len(self.train_x[0]) if self.train_x else 4)

    def fit(self, ins: FitIns) -> FitRes:
        """
        1. Receive global parameters
        2. Set local model
        3. Train locally
        4. Return updated parameters and metrics
        """
        self.model.set_parameters(ins.parameters)

        epochs = ins.config.get("local_epochs", self.local_epochs)
        lr = ins.config.get("learning_rate", self.learning_rate)

        final_loss = 0.0
        for _ in range(epochs):
            final_loss = self.model.train_step(self.train_x, self.train_y, lr=lr)

        eval_loss, eval_acc = self.model.evaluate(self.test_x, self.test_y)

        return FitRes(
            parameters=self.model.get_parameters(),
            num_examples=len(self.train_x),
            metrics={
                "cid": self.cid,
                "train_loss": final_loss,
                "val_loss": eval_loss,
                "val_accuracy": eval_acc,
                "epochs": epochs,
            },
        )

    def evaluate(self, ins: EvaluateIns) -> EvaluateRes:
        """
        1. Receive global parameters
        2. Evaluate on local test data
        3. Return loss, example count, and accuracy
        """
        self.model.set_parameters(ins.parameters)
        loss, accuracy = self.model.evaluate(self.test_x, self.test_y)

        return EvaluateRes(
            loss=loss,
            num_examples=len(self.test_x),
            metrics={
                "cid": self.cid,
                "accuracy": accuracy,
            },
        )


def create_client_app(
    num_clients: int = 3,
    samples_per_client: int = 100,
    seed: int = 42,
    local_epochs: int = 2,
    learning_rate: float = 0.05,
):
    """
    Factory creating a ClientApp with deterministic dataset partitions for each client.
    """
    from trustfl_core.flower_app import ClientApp

    client_datasets = {}
    for i in range(num_clients):
        cid = f"client_{i}"
        train_data = generate_synthetic_data(
            num_samples=samples_per_client,
            in_features=4,
            seed=seed + i * 10,
        )
        test_data = generate_synthetic_data(
            num_samples=max(20, samples_per_client // 4),
            in_features=4,
            seed=seed + 500 + i * 10,
        )
        client_datasets[cid] = (train_data, test_data)

    def client_fn(cid: str) -> TrustFLClient:
        if cid not in client_datasets:
            # Fallback partition
            train_data = generate_synthetic_data(num_samples=samples_per_client, seed=seed)
            test_data = generate_synthetic_data(num_samples=25, seed=seed + 99)
            client_datasets[cid] = (train_data, test_data)

        train_d, test_d = client_datasets[cid]
        return TrustFLClient(
            cid=cid,
            train_data=train_d,
            test_data=test_d,
            local_epochs=local_epochs,
            learning_rate=learning_rate,
        )

    return ClientApp(client_fn=client_fn)
