"""
Pure Python tiny deterministic neural network (linear classifier / multi-layer perceptron).
Designed with zero external heavy dependencies (no PyTorch/NumPy required), while maintaining
complete compatibility with Flower NDArrays parameter formats.
"""

from __future__ import annotations

import math
import random

# Parameters represented as List[List[float]]: [weights, biases]
Parameters = list[list[float]]


class TinyLinearModel:
    """
    Tiny Deterministic Linear Classifier:
    y = sigmoid(W * x + b)

    Input dimension: in_features
    Output dimension: 1 (binary classification)
    Parameters:
      w: list of in_features floats
      b: list of 1 float
    """

    def __init__(self, in_features: int = 4, seed: int = 42) -> None:
        self.in_features = in_features
        rng = random.Random(seed)
        # Deterministic weight initialization
        self.w: list[float] = [rng.uniform(-0.1, 0.1) for _ in range(in_features)]
        self.b: list[float] = [0.0]

    def get_parameters(self) -> Parameters:
        """Returns deep copy of model parameters."""
        return [list(self.w), list(self.b)]

    def set_parameters(self, parameters: Parameters) -> None:
        """Sets model parameters from list of parameter arrays."""
        if len(parameters) != 2:
            raise ValueError(f"Expected 2 parameter tensors [w, b], got {len(parameters)}")
        if len(parameters[0]) != self.in_features:
            raise ValueError(
                f"Expected weight size {self.in_features}, got {len(parameters[0])}"
            )
        if len(parameters[1]) != 1:
            raise ValueError(f"Expected bias size 1, got {len(parameters[1])}")

        self.w = list(parameters[0])
        self.b = list(parameters[1])

    @staticmethod
    def _sigmoid(z: float) -> float:
        # Clamp to avoid overflow
        z_clamped = max(min(z, 20.0), -20.0)
        return 1.0 / (1.0 + math.exp(-z_clamped))

    def forward(self, x: list[float]) -> float:
        """Computes single forward pass prediction."""
        dot = sum(wi * xi for wi, xi in zip(self.w, x, strict=False)) + self.b[0]
        return self._sigmoid(dot)

    def train_step(
        self,
        batch_x: list[list[float]],
        batch_y: list[float],
        lr: float = 0.05,
    ) -> float:
        """
        Executes one batch of gradient descent.
        Returns batch binary cross-entropy loss.
        """
        n = len(batch_x)
        if n == 0:
            return 0.0

        grad_w = [0.0] * self.in_features
        grad_b = 0.0
        total_loss = 0.0

        for x, y in zip(batch_x, batch_y, strict=False):
            pred = self.forward(x)
            # Binary Cross Entropy loss
            eps = 1e-12
            pred_clamped = max(min(pred, 1.0 - eps), eps)
            loss = -(y * math.log(pred_clamped) + (1.0 - y) * math.log(1.0 - pred_clamped))
            total_loss += loss

            # Derivative of BCE w.r.t logits (pred - y)
            err = pred - y
            for i in range(self.in_features):
                grad_w[i] += err * x[i]
            grad_b += err

        # Update weights
        for i in range(self.in_features):
            self.w[i] -= lr * (grad_w[i] / n)
        self.b[0] -= lr * (grad_b / n)

        return total_loss / n

    def evaluate(
        self, test_x: list[list[float]], test_y: list[float]
    ) -> tuple[float, float]:
        """
        Computes (loss, accuracy) over dataset.
        """
        if not test_x:
            return 0.0, 0.0

        total_loss = 0.0
        correct = 0
        eps = 1e-12

        for x, y in zip(test_x, test_y, strict=False):
            pred = self.forward(x)
            pred_clamped = max(min(pred, 1.0 - eps), eps)
            loss = -(y * math.log(pred_clamped) + (1.0 - y) * math.log(1.0 - pred_clamped))
            total_loss += loss

            predicted_class = 1.0 if pred >= 0.5 else 0.0
            if predicted_class == y:
                correct += 1

        n = len(test_x)
        return total_loss / n, correct / n


def generate_synthetic_data(
    num_samples: int = 100,
    in_features: int = 4,
    seed: int = 42,
    noise: float = 0.05,
) -> tuple[list[list[float]], list[float]]:
    """
    Generates deterministic synthetic linearly separable binary classification dataset.
    Decision boundary: sum(x[:in_features//2]) > sum(x[in_features//2:])
    """
    rng = random.Random(seed)
    x_data: list[list[float]] = []
    y_data: list[float] = []

    mid = in_features // 2
    for _ in range(num_samples):
        x = [rng.uniform(-1.0, 1.0) for _ in range(in_features)]
        score = sum(x[:mid]) - sum(x[mid:]) + rng.gauss(0, noise)
        y = 1.0 if score > 0 else 0.0
        x_data.append(x)
        y_data.append(y)

    return x_data, y_data
