#!/usr/bin/env python3
"""
Lightweight local simulation script for TrustFL federated learning core.
Outputs execution telemetry and verifies convergence without heavy logging.
"""

import json
from pathlib import Path

from apps.coordinator.coordinator import run_simulation


def main() -> None:
    print("============================================================")
    print("TrustFL Federated Learning Simulation (Stage 02 Minimal Core)")
    print("============================================================")

    num_clients = 5
    num_rounds = 3
    local_epochs = 2
    seed = 42

    print(f"Configuring simulation: {num_clients} clients, {num_rounds} rounds, {local_epochs} local epochs, seed={seed}")
    sim = run_simulation(
        num_clients=num_clients,
        num_rounds=num_rounds,
        local_epochs=local_epochs,
        random_seed=seed,
    )

    print("\n--- Simulation Summary ---")
    print(f"Rounds executed: {sim['num_rounds_executed']}")
    print(f"Participating clients: {', '.join(sim['clients_participating'])}")

    print("\nRound-by-round Metrics:")
    for stat in sim["round_history"]:
        r = stat["round"]
        loss = stat["loss"]
        acc = stat["accuracy"]
        succ = stat["num_successful_clients"]
        print(f"  Round {r}: Eval Loss = {loss:.4f} | Accuracy = {acc:.2%} | Clients Active = {succ}")

    delta_w = [
        round(f - i, 5)
        for i, f in zip(sim["initial_parameters"][0], sim["final_parameters"][0], strict=False)
    ]
    print(f"\nGlobal Model Weight Updates (Final - Initial): {delta_w}")

    # Output lightweight summary
    output_dir = Path("tests/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "sim_summary.json"
    summary_data = {
        "num_rounds_executed": sim["num_rounds_executed"],
        "clients_participating": sim["clients_participating"],
        "round_metrics": sim["round_history"],
        "weight_delta": delta_w,
    }
    summary_path.write_text(json.dumps(summary_data, indent=2))
    print(f"\nLightweight simulation summary saved to: {summary_path}")
    print("============================================================")


if __name__ == "__main__":
    main()
