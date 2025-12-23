import os
import sys
import yaml
import shutil
import argparse
import subprocess
import time
import tempfile
from sql_benchmarks.utils.hasher import generate_experiment_hash, generate_integrity_seal
from sql_benchmarks.utils.common import generate_partition_keys
from sql_benchmarks.utils.integrity_monitor import IntegrityMonitor
from sql_benchmarks.constants import (
    ROOT_DIR, 
    EXPERIMENTS_DIR, 
    ACTIVE_CONFIG_PATH, 
    CONFIG_ARCHIVE_DIR,
    DAGSTER_MODULE_TARGET
)


def run_automated(exp_hash, keys, staging_dir):
    print(f"[INFO] Launching {exp_hash} (Automated)...")
    print(f"       -> Environment: ACID Isolated Staging ({staging_dir})")
    start = time.time()
    
    overall_success = True
    
    # Set DAGSTER_HOME and PYTHONPATH to local paths in staging to prevent global pollution
    local_env = os.environ.copy()
    local_env["DAGSTER_HOME"] = os.path.join(staging_dir, "dagster_home")
    local_env["PYTHONPATH"] = staging_dir
    os.makedirs(local_env["DAGSTER_HOME"], exist_ok=True)
    
    if not keys: keys = [None]
    
    for pk in keys:
        if pk:
            print(f"       -> Triggering Partition: {pk}...")
            cmd = [sys.executable, "execute_run.py", "--partition", pk]
        else:
            print(f"       -> Triggering Unpartitioned Run...")
            cmd = [sys.executable, "execute_run.py", "--all"]

        try:
            # Execute in the staging directory context
            subprocess.run(cmd, check=True, cwd=staging_dir, env=local_env)
            print(f"          [SUCCESS] Done.")
        except subprocess.CalledProcessError as e:
            print(f"          [FAILED] Execution failed.")
            overall_success = False

    # Trigger Reporting Asset (Unpartitioned)
    print(f"       -> Triggering Reporting...")
    cmd = [sys.executable, "execute_run.py", "--reporting"]
    
    try:
        subprocess.run(cmd, check=True, cwd=staging_dir, env=local_env)
        print(f"          [SUCCESS] Done.")
    except subprocess.CalledProcessError as e:
        print(f"          [FAILED] Reporting Failed.")
        overall_success = False

    # Status Check
    print(f"[INFO] ACID Run Complete ({time.time() - start:.1f}s)")
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

        # B. Prepare Meta and Activation Logic
        if "meta" not in config: config["meta"] = {}
        config["meta"]["experiment_id"] = exp_hash

        # C. ACID Isolation Staging (Genesis Snapshot)
        with tempfile.TemporaryDirectory() as staging_dir:
            print(f"[INFO] Entering Staging Area: {staging_dir}")
            
            # 1. Snapshot Harness
            # Note: We copy the package and the entry point script
            shutil.copytree(os.path.join(ROOT_DIR, "sql_benchmarks"), os.path.join(staging_dir, "sql_benchmarks"), dirs_exist_ok=True)
            shutil.copy(os.path.join(ROOT_DIR, "execute_run.py"), os.path.join(staging_dir, "execute_run.py"))
            
            # 2. Snapshot Scenario SQL
            scenario_rel = config.get("meta", {}).get("scenario_path", "")
            scenario_src = os.path.normpath(os.path.join(ROOT_DIR, "sql_benchmarks", "scripts", "sql", scenario_rel))
            scenario_dst = os.path.join(staging_dir, "sql_benchmarks", "scripts", "sql", scenario_rel)
            if os.path.exists(scenario_src):
                os.makedirs(os.path.dirname(scenario_dst), exist_ok=True)
                shutil.copytree(scenario_src, scenario_dst, dirs_exist_ok=True)
            
            # 3. Snapshot Data (If local data is needed, we'd copy it here, but assets handle loading)
            
            # 4. Activate Config inside staging
            staging_active_path = os.path.join(staging_dir, "sql_benchmarks", "experiments", "active.yaml")
            os.makedirs(os.path.dirname(staging_active_path), exist_ok=True)
            with open(staging_active_path, 'w') as f:
                yaml.dump(config, f, sort_keys=False)

            # 5. Initialize Integrity Monitor to watch the ROOT project for drift
            # This detects if YOU change a file in your project during the run.
            from sql_benchmarks.constants import PACKAGE_DIR
            monitor = IntegrityMonitor(PACKAGE_DIR)

            # 6. EXECUTE (Isolated)
            matrix = config.get("execution", {}).get("matrix") or config.get("execution", {}).get("dimensions")
            keys = generate_partition_keys(matrix)
            
            success = False
            if auto_mode:
                success = run_automated(exp_hash, keys, staging_dir)
            else:
                print(f"[INFO] ACTIVATED: {exp_hash} (Isolated)")
                print(f"       -> Staging Dir: {staging_dir}")
                input("Press Enter when done (Simulating manual run in staging environment)...")
                success = True

            # 7. Check for Semantic Drift during execution
            drift = monitor.check_drift()
            # We expect results and logs to be ADDED, but no existing code should be MODIFIED or DELETED
            malicious_drift = [d for d in drift if ("MODIFIED" in d or "DELETED" in d) and "experiments/results" not in d]
            if malicious_drift:
                print(f"[CRITICAL] ACID VIOLATION: Source code tampered with during execution!")
                for d in malicious_drift: print(f"           !! {d}")
                
                # PERSIST THE EVIDENCE: Move the infected staging area to a special violation folder
                violation_dir = os.path.join(ROOT_DIR, "sql_benchmarks", "experiments", "violations", f"violation_{exp_hash}_{int(time.time())}")
                os.makedirs(os.path.dirname(violation_dir), exist_ok=True)
                shutil.copytree(staging_dir, violation_dir)
                print(f"           !! EVIDENCE PERSISTED: {violation_dir}")
                
                success = False

            # 8. ATOMIC COMMIT (Commit results only on success and verification)
            if success:
                # Generate Seal inside staging area
                # We need to ensure the results actually ended up in staging_dir/sql_benchmarks/experiments/results/<exp_hash>
                staging_results_dir = os.path.normpath(os.path.join(staging_dir, "sql_benchmarks", "experiments", "results", exp_hash))
                
                if os.path.exists(staging_results_dir):
                    # 1. Final Genesis Snapshot (Evidence for Career)
                    # Copy the used harness from staging area into the results capsule
                    staging_src_dir = os.path.join(staging_results_dir, "src")
                    os.makedirs(staging_src_dir, exist_ok=True)
                    shutil.copytree(os.path.join(staging_dir, "sql_benchmarks"), os.path.join(staging_src_dir, "sql_benchmarks"), dirs_exist_ok=True)
                    shutil.copy(os.path.join(staging_dir, "execute_run.py"), os.path.join(staging_src_dir, "execute_run.py"))

                    # 2. Seal it (Including the newly added src snapshot)
                    seal = generate_integrity_seal(staging_results_dir)
                    with open(os.path.join(staging_results_dir, "integrity.seal"), "w") as f:
                        f.write(seal)
                    
                    # Final Commit to repository
                    repo_results_dir = os.path.join(ROOT_DIR, "sql_benchmarks", "experiments", "results", exp_hash)
                    os.makedirs(os.path.dirname(repo_results_dir), exist_ok=True)
                    if os.path.exists(repo_results_dir): shutil.rmtree(repo_results_dir)
                    shutil.copytree(staging_results_dir, repo_results_dir)
                    
                    # Also archive config to registry and human library
                    shutil.copy(staging_active_path, registry_path)
                    lib_path = os.path.join(EXPERIMENTS_DIR, "archive", filename)
                    shutil.copy(staging_active_path, lib_path)
                    
                    print(f"[INFO] ACID COMMIT: Experiment {exp_hash} sealed and saved.")
                    print(f"       -> Dashboard: {os.path.join(repo_results_dir, f'dashboard_{exp_hash}.html')}")
                else:
                    print(f"[ERROR] Run finished but results not found in staging area.")
                    success = False

        if not success and not auto_mode:
             sys.exit(0) # Interactive user cancelled
        elif not success and auto_mode:
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