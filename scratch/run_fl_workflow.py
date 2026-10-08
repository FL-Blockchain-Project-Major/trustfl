import sys
from pathlib import Path
from apps.coordinator.coordinator import run_simulation
from apps.client.client import create_client_app

def main():
    print("--- TRUSTFL FEDERATED LEARNING WORKFLOW EXECUTION ---")
    
    num_clients = 3
    num_rounds = 3
    local_epochs = 2
    failing_clients = ["client_2"] # 1 failing client, 2 successful
    
    print(f"Config: {num_clients} clients total, {num_rounds} rounds, {local_epochs} local epochs")
    print(f"Failing clients configured: {failing_clients}")
    
    sim = run_simulation(
        num_clients=num_clients,
        num_rounds=num_rounds,
        local_epochs=local_epochs,
        random_seed=42,
        failing_clients=failing_clients,
    )
    
    print("\n[VERIFICATION RESULTS]")
    print(f"Global Initial Parameters (sample): {sim['initial_parameters'][0][:5]}")
    print(f"Global Final Parameters (sample): {sim['final_parameters'][0][:5]}")
    
    param_changed = sim['initial_parameters'] != sim['final_parameters']
    print(f"Global parameters actually changed: {param_changed}")
    
    print("\n--- ROUND HISTORY ---")
    for r in sim["round_history"]:
        rnd = r["round"]
        loss = r["loss"]
        acc = r["accuracy"]
        succ_clients = r["num_successful_clients"]
        print(f"Round {rnd}:")
        print(f"  Aggregated Eval Loss: {loss:.4f}")
        print(f"  Aggregated Eval Accuracy: {acc:.4f}")
        print(f"  Successful Clients: {succ_clients} (Expected: {num_clients - len(failing_clients)})")
        # Print metrics returned from clients
        if "metrics" in r:
            print(f"  Metrics: {r['metrics']}")
            
    print("\n--- FAILED CLIENT HANDLING ---")
    expected_active = num_clients - len(failing_clients)
    actual_active = sim["round_history"][0]["num_successful_clients"]
    print(f"Expected Active: {expected_active}, Actual Active: {actual_active}")
    if actual_active == expected_active:
        print("Failed clients were handled correctly (did not block aggregation).")
    else:
        print("Failed clients handling mismatch!")

if __name__ == "__main__":
    main()
