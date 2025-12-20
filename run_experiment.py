import os
import sys
import yaml
import shutil
import argparse
import subprocess
import time
from sql_benchmarks.utils.hasher import generate_experiment_hash
from sql_benchmarks.utils.common import generate_partition_keys
from sql_benchmarks.constants import (
    ROOT_DIR, 
    EXPERIMENTS_DIR, 
    ACTIVE_CONFIG_PATH, 
    CONFIG_ARCHIVE_DIR,
    DAGSTER_MODULE_TARGET
)


def run_automated(exp_hash, keys):
    print(f"[INFO] Launching {exp_hash} (Automated)...")
    start = time.time()
    
    overall_success = True
    
    if not keys: keys = [None]
    
    for pk in keys:
        if pk:
            print(f"       -> Triggering Partition: {pk}...")
            # Use local runner script (SDK Wrapper)
            cmd = [sys.executable, "execute_run.py", "--partition", pk]
        else:
            print(f"       -> Triggering Unpartitioned Run...")
            cmd = [sys.executable, "execute_run.py", "--all"]

        try:
            # FIX: Do not capture output. Stream it to stdout to avoid buffer deadlocks.
            subprocess.run(cmd, check=True)
            print(f"          [SUCCESS] Done.")
        except subprocess.CalledProcessError as e:
            print(f"          [FAILED] Execution failed.")
            overall_success = False

    # NEW: Trigger Reporting Asset (Unpartitioned)
    print(f"       -> Triggering Reporting...")
    cmd = [sys.executable, "execute_run.py", "--reporting"]
    
    try:
        subprocess.run(cmd, check=True)
        print(f"          [SUCCESS] Done.")
    except subprocess.CalledProcessError as e:
        print(f"          [FAILED] Reporting Failed.")
        overall_success = False

    print(f"[INFO] Experiment Complete ({time.time() - start:.1f}s)")
    return overall_success


def process_queue(target_input, auto_mode=False):
    # 1. STRICT PATH RESOLUTION
    target_path = None
    
    # Check 1: Is the input an absolute or relative path that exists?
    if os.path.exists(target_input):
        target_path = os.path.abspath(target_input)
    
    # Check 2: Is the input a symbolic folder name within EXPERIMENTS_DIR?
    # This handles 'queue' or 'archive' being passed as simple names.
    elif os.path.exists(os.path.join(EXPERIMENTS_DIR, target_input)):
        target_path = os.path.join(EXPERIMENTS_DIR, target_input)
    
    if target_path is None:
        print(f"[ERROR] CRITICAL: Target not found: {target_input}")
        return

    # 2. CHECK TARGET TYPE (File vs. Directory)
    queue = []
    if os.path.isfile(target_path):
        queue.append(target_path)
    elif os.path.isdir(target_path):
        print(f"[INFO] Scanning directory: {target_path}")
        # Support both .yaml and .yml, ignore .processed files
        files = sorted([
            os.path.join(target_path, f) 
            for f in os.listdir(target_path) 
            if f.endswith((".yaml", ".yml")) and not f.endswith(".processed")
        ])
        queue.extend(files)

    if not queue:
        print(f"[WARN] No YAML files found in {target_path}. Skipping.")
        return

    print(f"[INFO] Queue size: {len(queue)}")
    print(f"[INFO] Mode: {'AUTOMATED' if auto_mode else 'INTERACTIVE (UI)'}")

    # 3. EXECUTE LOOP
    overall_queue_success = True
    for i, config_file in enumerate(queue):
        filename = os.path.basename(config_file)
        print(f"\n" + "-" * 60)
        print(f"[{i+1}/{len(queue)}] PREPARING: {filename}")
        
        try:
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            if not config or not isinstance(config, dict):
                print(f"[WARN] Skipping empty/invalid YAML: {filename}")
                continue
        except Exception as e:
            print(f"[ERROR] Invalid YAML: {e}")
            overall_queue_success = False
            continue

        exp_hash = generate_experiment_hash(config, ROOT_DIR)
        
        # A. Check Registry
        registry_path = os.path.join(CONFIG_ARCHIVE_DIR, f"config_{exp_hash}.yaml")
        if os.path.exists(registry_path):
            print(f"[INFO] SKIPPING: Experiment {exp_hash} already exists in registry.")
            continue

        # B. Activate
        if "meta" not in config: config["meta"] = {}
        config["meta"]["experiment_id"] = exp_hash

        with open(ACTIVE_CONFIG_PATH, 'w') as f:
            yaml.dump(config, f, sort_keys=False)

        # C. Run (Using Shared Logic)
        execution = config.get("execution", {})
        matrix = execution.get("matrix") or execution.get("dimensions")
        keys = generate_partition_keys(matrix)
        
        success = False
        if auto_mode:
            success = run_automated(exp_hash, keys)
        else:
            print(f"[INFO] ACTIVATED: {exp_hash}")
            if keys:
                print(f"[INFO] Partitions found: {keys}")
                print(f"       -> ACTION: In UI, click 'Materialize All' -> Select Partition")
            input("Press Enter when done...")
            success = True

        # D. Archive
        if success:
            shutil.copy(ACTIVE_CONFIG_PATH, registry_path)
            print(f"[INFO] Archived {exp_hash} to registry.")
        elif not auto_mode:
            sys.exit(0) # Interactive user cancelled
        else:
            # Automated mode failure
            overall_queue_success = False

    return overall_queue_success

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SQL Benchmarks Experiment Runner",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument(
        "target", 
        help="Path to a YAML file, 'queue', or 'archive'."
    )
    
    parser.add_argument(
        "--auto", 
        action="store_true", 
        help="Run in HEADLESS mode."
    )

    args = parser.parse_args()
    
    success = process_queue(args.target, args.auto)
    
    # If process_queue returns False (failed), exit with status 1
    if not success:
        sys.exit(1)