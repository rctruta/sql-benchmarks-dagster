import pandas as pd
import yaml
import shutil
import os
import sys
from dagster import DagsterInstance, DagsterEventType, DagsterRunStatus

# Import your system constants
from sql_benchmarks.constants import ACTIVE_CONFIG_PATH, CONFIG_ARCHIVE_DIR, RESULTS_DIR

def get_instance():
    """
    Connects to Dagster. Automatically defaults to ~/.dagster if env var is missing.
    """
    if "DAGSTER_HOME" not in os.environ:
        # Auto-fix the environment variable issue
        default_home = os.path.expanduser("~/.dagster")
        os.environ["DAGSTER_HOME"] = default_home
        print(f"⚠️  DAGSTER_HOME not set. Defaulting to: {default_home}")
    
    try:
        return DagsterInstance.get()
    except Exception as e:
        print(f"❌ Failed to load Dagster Instance: {e}")
        sys.exit(1)

def extract_and_snapshot():
    # 1. READ TARGET ID
    try:
        with open(ACTIVE_CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f)
        target_id = config.get("meta", {}).get("experiment_id")
        if not target_id:
            print("❌ 'experiment_id' missing in active.yaml.")
            return
    except FileNotFoundError:
        print(f"❌ Config not found at {ACTIVE_CONFIG_PATH}")
        return

    # 2. CONNECT
    instance = get_instance()
    print(f"🔌 Connected to DB: {instance.root_directory}")
    print(f"🎯 Looking for Experiment ID: {target_id}")

    records = []
    found_ids = set() # Track what we actually see
    
    # 3. SCAN HISTORY
    runs = instance.get_runs(limit=50)
    
    for run in runs:
        # Skip failed runs (unless you want partial data)
        if run.status != DagsterRunStatus.SUCCESS:
            continue

        logs = instance.all_logs(run.run_id)
        for log in logs:
            if not log.is_dagster_event or log.dagster_event.event_type != DagsterEventType.ASSET_MATERIALIZATION:
                continue
            
            mat = log.dagster_event.step_materialization_data.materialization
            meta = mat.metadata
            
            # Check ID
            stored_id_val = meta.get("experiment_id")
            # Handle Dagster's value wrapping
            if hasattr(stored_id_val, 'value'):
                stored_id = stored_id_val.value
            else:
                stored_id = stored_id_val

            # Track what we found for debugging
            if stored_id:
                found_ids.add(stored_id)

            # Strict Match
            if stored_id != target_id:
                continue
            
            # Logic: If we are here, we have a match.
            def get_val(key): 
                val = meta.get(key)
                return val.value if hasattr(val, 'value') else val

            # Only verify duration exists
            if not get_val("duration_seconds"): continue

            row = {
                "timestamp": pd.to_datetime(log.timestamp, unit='s'),
                "experiment_id": stored_id,
                "asset": mat.asset_key.path[-1],
                "partition": run.tags.get("dagster/partition", "unknown"),
                "duration_seconds": get_val("duration_seconds"),
                "orphans": get_val("trace_orphans"),
                "rows": get_val("trace_rows"),
                "engine": get_val("config_engine")
            }
            # Engine Fallback
            if not row["engine"]:
                if "duckdb" in row["asset"]: row["engine"] = "duckdb"
                elif "pg_" in row["asset"]: row["engine"] = "postgres"

            records.append(row)

    # 4. SAVE OR DIAGNOSE
    if records:
        df = pd.DataFrame(records)
        # Deduplicate (keep latest)
        df = df.sort_values("timestamp").drop_duplicates(subset=["asset", "partition"], keep="last")
        df = df.sort_values(by=["engine", "rows", "orphans", "asset"])
        
        # Create dedicated folder for this ID
        result_dir = os.path.join(RESULTS_DIR, target_id)
        os.makedirs(result_dir, exist_ok=True)

        csv_path = os.path.join(result_dir, f"results_{target_id}.csv")
        yaml_path = os.path.join(result_dir, f"config_{target_id}.yaml")
        
        df.to_csv(csv_path, index=False)
        shutil.copy(ACTIVE_CONFIG_PATH, yaml_path)
        
        print(f"\n✅ SUCCESS!")
        print(f"   📂 Saved to: {result_dir}")
        print(f"   📊 Rows captured: {len(df)}")
    else:
        print(f"\n❌ FAILURE: No runs matched ID '{target_id}'.")
        print("🔎 DEBUG: Here are the Experiment IDs actually found in your DB:")
        if found_ids:
            for fid in found_ids:
                print(f"   - {fid}")
            print("\n👉 Mismatch Detected: Your 'active.yaml' has a different ID than your Database.")
            print("   Action: Run 'python run_experiment.py ...' to sync them, then 'Reload Definitions' & 'Backfill'.")
        else:
            print("   (No experiment IDs found. Did the backfill run successfully?)")

if __name__ == "__main__":
    extract_and_snapshot()