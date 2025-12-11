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
    print(f"🚀 Launching {exp_hash} (Automated)...")
    start = time.time()
    
    if not keys: keys = [None]
    
    for pk in keys:
        if pk:
            print(f"   ▶ Triggering Partition: {pk}...")
            cmd = [
                "dagster", "asset", "materialize", 
                "-m", DAGSTER_MODULE_TARGET, 
                "--select", "*",
                "--partition", pk 
            ]
        else:
            print(f"   ▶ Triggering Unpartitioned Run...")
            cmd = [
                "dagster", "asset", "materialize", 
                "-m", DAGSTER_MODULE_TARGET, 
                "--select", "*"
            ]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"     ✅ Done.")
        except subprocess.CalledProcessError as e:
            print(f"     ❌ Failed.")
            if e.stderr:
                print(f"🔎 Error: {e.stderr.decode('utf-8')[-500:]}")

    print(f"🏁 Experiment Complete ({time.time() - start:.1f}s)")
    return True

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
        print(f"❌ CRITICAL: Target not found: {target_input}")
        return

    # 2. CHECK TARGET TYPE (File vs. Directory)
    queue = []
    if os.path.isfile(target_path):
        queue.append(target_path)
    elif os.path.isdir(target_path):
        print(f"📂 Scanning directory: {target_path}")
        # Support both .yaml and .yml, ignore .processed files
        files = sorted([
            os.path.join(target_path, f) 
            for f in os.listdir(target_path) 
            if f.endswith((".yaml", ".yml")) and not f.endswith(".processed")
        ])
        queue.extend(files)

    if not queue:
        print(f"⚠️  No YAML files found in {target_path}. Skipping.")
        return

    print(f"📋 Queue size: {len(queue)}")
    print(f"⚙️  Mode: {'AUTOMATED' if auto_mode else 'INTERACTIVE (UI)'}")

    # 3. EXECUTE LOOP
    for i, config_file in enumerate(queue):
        filename = os.path.basename(config_file)
        print(f"\n------------------------------------------------------------")
        print(f"[{i+1}/{len(queue)}] PREPARING: {filename}")
        
        try:
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            if not config or not isinstance(config, dict):
                print(f"⚠️  Skipping empty/invalid YAML: {filename}")
                continue
        except Exception as e:
            print(f"❌ Invalid YAML: {e}")
            continue

        exp_hash = generate_experiment_hash(config, ROOT_DIR)
        
        # A. Check Registry
        registry_path = os.path.join(CONFIG_ARCHIVE_DIR, f"config_{exp_hash}.yaml")
        if os.path.exists(registry_path):
            print(f"✨ SKIPPING: Experiment {exp_hash} already exists in registry.")
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
            print(f"🚀 ACTIVATED: {exp_hash}")
            if keys:
                print(f"⚠️  Partitions found: {keys}")
                print(f"👉 ACTION: In UI, click 'Materialize All' -> Select Partition")
            input("Press Enter when done...")
            success = True

        # D. Archive
        if success:
            shutil.copy(ACTIVE_CONFIG_PATH, registry_path)
            print(f"💾 Archived {exp_hash} to registry.")
        elif not auto_mode:
            sys.exit(0)

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
    
    process_queue(args.target, args.auto)