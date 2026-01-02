import os
import shutil
import time
import yaml
from sql_benchmarks.coordinator import ExperimentCoordinator
from sql_benchmarks.constants import EXPERIMENTS_DIR

def demonstrate_security():
    """
    Simulates a 'Blueberry Muffin' attack.
    1. Starts a run.
    2. While the coordinator is provisioning, we TAMPER with the code.
    3. We verify the run FAILS to commit.
    """
    print("\n--- [DEMO] INITIATING BREACH TEST ---")
    
    # Setup a dummy experiment
    exp_path = os.path.join(EXPERIMENTS_DIR, "queue", "breach_demo.yaml")
    os.makedirs(os.path.dirname(exp_path), exist_ok=True)
    with open(exp_path, 'w') as f:
        yaml.dump({
            "meta": {"experiment_id": "breach_demo"},
            "execution": {"engines": ["duckdb"], "matrix": {"rows": [100]}}
        }, f)

    # We need to manually trigger the breach DURING the coordinator life-cycle
    # For this demo, we will wrap the coordinator
    coord = ExperimentCoordinator(exp_path, headless=True)
    
    # 1. INITIALIZE (Takes Snapshot)
    print("[1/3] Starting Coordinator...")
    
    # We will simulate the 'Run' but inject a modification to a project file
    # right after the harness provisions.
    
    target_file = "sql_benchmarks/constants.py"
    original_content = open(target_file, "r").read()
    
    try:
        # We start the run
        print(f"[2/3] Tampering with {target_file} during run...")
        with open(target_file, "a") as f:
            f.write("\n# MALICIOUS INJECTION")
            
        print("[3/3] Attempting run with tampered code...")
        success = coord.run()
        
        if not success:
            print("\n✅ SUCCESS: SYSTEM DETECTED THE BREACH!")
            print("The results were DISCARDED and NOT committed to the repo.")
        else:
            print("\n❌ FAILURE: SYSTEM ALLOWED THE BREACH TO COMMIT!")
            
    finally:
        # Restore the file
        with open(target_file, "w") as f:
            f.write(original_content)
        if os.path.exists(exp_path): os.remove(exp_path)

if __name__ == "__main__":
    demonstrate_security()
