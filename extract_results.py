import polars as pl
import yaml
import shutil
import os
import sys
from datetime import datetime
from dagster import DagsterInstance, DagsterEventType, DagsterRunStatus

# STRICT IMPORTS
from sql_benchmarks.constants import ACTIVE_CONFIG_PATH, CONFIG_ARCHIVE_DIR, RESULTS_DIR

def get_instance():
    if "DAGSTER_HOME" not in os.environ:
        default_home = os.path.expanduser("~/.dagster")
        os.environ["DAGSTER_HOME"] = default_home
    
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
    
    # 3. SCAN HISTORY
    runs = instance.get_runs(limit=50)
    
    for run in runs:
        if run.status != DagsterRunStatus.SUCCESS:
            continue

        logs = instance.all_logs(run.run_id)
        for log in logs:
            if not log.is_dagster_event or log.dagster_event.event_type != DagsterEventType.ASSET_MATERIALIZATION:
                continue
            
            mat = log.dagster_event.step_materialization_data.materialization
            meta = mat.metadata
            
            # Check Experiment ID
            stored_id_val = meta.get("experiment_id")
            stored_id = stored_id_val.value if hasattr(stored_id_val, 'value') else stored_id

            if stored_id != target_id:
                continue
            
            # --- FIX: Corrected Helper Function ---
            def get_val(key, default=None): 
                val = meta.get(key)
                if val is None:
                    return default
                # Handle Dagster's MetadataValue wrapper
                return val.value if hasattr(val, 'value') else val

            # Skip if duration is missing
            if not get_val("duration_seconds"): continue

            # Build Row with Safe Defaults
            # We explicitly cast to ensure Polars schema consistency
            try:
                row = {
                    "timestamp": datetime.fromtimestamp(log.timestamp),
                    "experiment_id": stored_id,
                    "asset": mat.asset_key.path[-1],
                    "partition": run.tags.get("dagster/partition", "unknown"),
                    "duration_seconds": float(get_val("duration_seconds", 0.0)),
                    "orphans": float(get_val("trace_orphans", 0.0)),
                    "rows": int(get_val("trace_rows", 0)),
                    "engine": str(get_val("config_engine", ""))
                }
            except (ValueError, TypeError) as e:
                print(f"⚠️ Skipping row due to type error: {e}")
                continue
            
            # Fallback for Engine Name
            if not row["engine"]:
                if "duckdb" in row["asset"]: row["engine"] = "duckdb"
                elif "pg_" in row["asset"]: row["engine"] = "postgres"

            records.append(row)

    # 4. SAVE & ARCHIVE
    if records:
        df = pl.DataFrame(records)
        
        # Deduplicate
        df = df.sort("timestamp").unique(subset=["asset", "partition"], keep="last")
        df = df.sort(["engine", "rows", "orphans", "asset"])
        
        # Prepare Folders
        result_dir = os.path.join(RESULTS_DIR, target_id)
        os.makedirs(result_dir, exist_ok=True)
        os.makedirs(CONFIG_ARCHIVE_DIR, exist_ok=True)

        # Paths
        csv_path = os.path.join(result_dir, f"results_{target_id}.csv")
        results_config_path = os.path.join(result_dir, f"config_{target_id}.yaml")
        registry_path = os.path.join(CONFIG_ARCHIVE_DIR, f"config_{target_id}.yaml")
        
        # Write
        df.write_csv(csv_path)
        shutil.copy(ACTIVE_CONFIG_PATH, results_config_path)
        shutil.copy(ACTIVE_CONFIG_PATH, registry_path)

        print(f"\n✅ SUCCESS!")
        print(f"   📊 Data:     {csv_path}")
        print(f"   💾 Registry: {registry_path}")
    else:
        print(f"\n❌ FAILURE: No runs matched ID '{target_id}'.")

if __name__ == "__main__":
    extract_and_snapshot()