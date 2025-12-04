import os
import sys
import yaml
import shutil
import argparse
import subprocess
import time
from sql_benchmarks.utils.hasher import generate_experiment_hash
from sql_benchmarks.constants import (
    ROOT_DIR, 
    EXPERIMENTS_DIR, 
    ACTIVE_CONFIG_PATH, 
    CONFIG_ARCHIVE_DIR,
    DAGSTER_MODULE_TARGET
)

def run_interactive(exp_hash):
    """Pauses execution so the user can run the job in the Dagster UI."""
    print(f"🚀 ACTIVATED: {exp_hash}")
    print(f"👉 ACTION: Go to Dagster UI -> 'Reload Definitions' -> 'Materialize All'")
    try:
        input(f"⌨️  Press [ENTER] once the run is GREEN (or Ctrl+C to stop)...")
        return True
    except KeyboardInterrupt:
        print("\n🛑 Stopping queue.")
        return False

def run_automated(exp_hash):
    """Automatically triggers the job via Dagster CLI."""
    print(f"🚀 Launching {exp_hash} (Automated)...")
    start = time.time()
    try:
        cmd = [
            "dagster", "asset", "materialize", 
            "-m", DAGSTER_MODULE_TARGET, 
            "--select", "*"
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✅ Success ({time.time() - start:.1f}s)")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed.")
        if e.stderr:
            print(f"🔎 Error: {e.stderr.decode('utf-8')[-500:]}")
        return False

def process_queue(target_input, auto_mode=False):
    # 1. SMART PATH RESOLUTION
    if os.path.exists(target_input):
        target_path = os.path.abspath(target_input)
    else:
        potential_path = os.path.join(EXPERIMENTS_DIR, target_input)
        if os.path.exists(potential_path):
            target_path = potential_path
        else:
            print(f"❌ Target not found: {target_input}")
            return

    # 2. BUILD QUEUE
    queue = []
    if os.path.isfile(target_path):
        queue.append(target_path)
    elif os.path.isdir(target_path):
        print(f"📂 Scanning directory: {target_path}")
        files = sorted([
            os.path.join(target_path, f) 
            for f in os.listdir(target_path) 
            if f.endswith(".yaml") or f.endswith(".yml")
        ])
        queue.extend(files)

    if not queue:
        print("⚠️  No YAML files found.")
        return

    print(f"📋 Queue size: {len(queue)}")
    print(f"⚙️  Mode: {'AUTOMATED' if auto_mode else 'INTERACTIVE (UI)'}")

    # 3. EXECUTE LOOP
    for i, config_file in enumerate(queue):
        filename = os.path.basename(config_file)
        print(f"\n------------------------------------------------------------")
        print(f"[{i+1}/{len(queue)}] PREPARING: {filename}")
        
        # A. Load & Hash
        try:
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            
            # --- FIX: Handle Empty or Invalid Files ---
            if not config or not isinstance(config, dict):
                print(f"⚠️  Skipping empty or invalid YAML: {filename}")
                continue
                
        except Exception as e:
            print(f"❌ Invalid YAML: {e}")
            continue

        exp_hash = generate_experiment_hash(config, ROOT_DIR)
        
        # B. Check Registry
        registry_path = os.path.join(CONFIG_ARCHIVE_DIR, f"config_{exp_hash}.yaml")
        if os.path.exists(registry_path):
            print(f"✨ SKIPPING: Experiment {exp_hash} already exists in registry.")
            continue

        # C. Activate
        if "meta" not in config: config["meta"] = {}
        config["meta"]["experiment_id"] = exp_hash

        with open(ACTIVE_CONFIG_PATH, 'w') as f:
            yaml.dump(config, f, sort_keys=False)

        # D. Run
        success = False
        if auto_mode:
            success = run_automated(exp_hash)
        else:
            success = run_interactive(exp_hash)

        # E. Archive
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
        help="Path to a YAML file or a folder of YAML configs (e.g., 'queue')."
    )
    
    parser.add_argument(
        "--auto", 
        action="store_true", 
        help="Run in HEADLESS mode.\n"
             "Automatically triggers 'dagster asset materialize' for each config.\n"
             "Default: INTERACTIVE mode (pauses for you to use the UI)."
    )

    args = parser.parse_args()
    
    process_queue(args.target, args.auto)