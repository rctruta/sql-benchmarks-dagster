import os
import sys
import yaml
from sql_benchmarks.utils.hasher import generate_experiment_hash
from sql_benchmarks.constants import (
    ROOT_DIR, 
    EXPERIMENTS_DIR, 
    ACTIVE_CONFIG_PATH, 
    CONFIG_ARCHIVE_DIR
)

def run(filename):
    # Allow running from just filename OR full path
    if os.path.exists(filename):
        source_path = filename
    else:
        source_path = os.path.join(EXPERIMENTS_DIR, filename)
    
    if not os.path.exists(source_path):
        print(f"❌ File not found: {source_path}")
        return

    # 1. Load Candidate Config
    with open(source_path, 'r') as f:
        config = yaml.safe_load(f)

    # 2. Calculate Identity (Semantic Hash)
    exp_hash = generate_experiment_hash(config, ROOT_DIR)
    print(f"🔑 Calculated Hash: {exp_hash}")
    
    # 3. CHECK REGISTRY (The Cache Logic)
    # We check if the config snapshot already exists in our archive.
    archived_config = os.path.join(CONFIG_ARCHIVE_DIR, f"config_{exp_hash}.yaml")
    
    if os.path.exists(archived_config):
        print(f"✨ CACHE HIT: Experiment {exp_hash} already exists in registry.")
        print(f"   See: {archived_config}")
        print("   🚀 Skipping execution.")
        return

    # 4. Activate (If new)
    # We ONLY inject the ID. We do NOT inject the source filename.
    if "meta" not in config: config["meta"] = {}
    config["meta"]["experiment_id"] = exp_hash

    with open(ACTIVE_CONFIG_PATH, 'w') as f:
        yaml.dump(config, f, sort_keys=False)

    print(f"✅ ACTIVATED: {exp_hash}")
    print("👉 ACTION: Reload Definitions in Dagster and Launch Backfill.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_experiment.py <config_file.yaml>")
    else:
        run(sys.argv[1])