from apps.coordinator.coordinator import run_simulation


def main():
    sim = run_simulation(
        num_clients=3,
        num_rounds=3,
        failing_clients=["client_2"],
    )
    for i, r in enumerate(sim["round_history"]):
        print(f"R{i+1} Aggregated Loss: {r['loss']:.4f}, Acc: {r['accuracy']:.4f}, Clients: {r['num_successful_clients']}")

if __name__ == "__main__":
    main()
