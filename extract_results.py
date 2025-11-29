import pandas as pd
import yaml
import shutil
import os
import sys
from dagster import DagsterInstance, DagsterEventType, DagsterRunStatus

from sql_benchmarks.constants import ROOT_DIR, ACTIVE_CONFIG_PATH, CONFIG_ARCHIVE_DIR, RESULTS_DIR

def extract_and_snapshot():
    # 1. READ ACTIVE CONFIG
    try:
        with open(ACTIVE_CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f)
        target_id = config.get("meta", {}).get("experiment_id")
        if not target_id:
            print("❌ 'experiment_id' missing in active.yaml.")
            return
        print(f"🎯 Looking for Target Hash: {target_id}")
        
    except FileNotFoundError:
        print(f"❌ Could not find active config at: {ACTIVE_CONFIG_PATH}")
        return

    # 2. CONNECT
    try:
        instance = DagsterInstance.get()
    except Exception:
        print("❌ CRITICAL: Run 'export DAGSTER_HOME=~/.dagster'")
        return

    records = []
    found_ids = set() # Debugging set
    
    # 3. SCAN HISTORY
    runs = instance.get_runs(limit=100)
    print(f"🔎 Scanning {len(runs)} recent runs...")

    for run in runs:
        if run.status != DagsterRunStatus.SUCCESS:
            continue

        logs = instance.all_logs(run.run_id)
        
        for log in logs:
            if not log.is_dagster_event or log.dagster_event.event_type != DagsterEventType.ASSET_MATERIALIZATION:
                continue
            
            mat = log.dagster_event.step_materialization_data.materialization
            meta = mat.metadata
            
            # --- DEBUGGING LOGIC ---
            # Capture whatever ID is actually there
            stored_id = meta.get("experiment_id")
            if stored_id:
                found_ids.add(stored_id.value)
            
            # Match Logic
            if not stored_id or stored_id.value != target_id:
                continue
            
            # If match, check for duration
            if "duration_seconds" not in meta:
                continue

            def get_val(key): return meta[key].value if key in meta else None
            asset_name = mat.asset_key.path[-1]

            row = {
                "timestamp": pd.to_datetime(log.timestamp, unit='s'),
                "experiment_id": stored_id.value,
                "asset": asset_name,
                "partition": run.tags.get("dagster/partition", "unknown"),
                "duration_seconds": get_val("duration_seconds"),
                "orphans": get_val("config_orphans"),
                "rows": get_val("config_rows"),
                "engine": get_val("config_engine"),
            }
            if not row["engine"]:
                if "duckdb" in asset_name: row["engine"] = "duckdb"
                elif "pg_" in asset_name: row["engine"] = "postgres"

            records.append(row)

    # 4. SAVE OR DEBUG
    if records:
        df = pd.DataFrame(records)
        df = df.sort_values(by=["engine", "rows", "orphans", "asset"])
        
        csv_path = os.path.join(RESULTS_DIR, f"results_{target_id}.csv")
        yaml_path = os.path.join(CONFIG_ARCHIVE_DIR, f"config_{target_id}.yaml")
        
        df.to_csv(csv_path, index=False)
        print(f"\n✅ DATA ARCHIVED: {csv_path}")
        
        shutil.copy(ACTIVE_CONFIG_PATH, yaml_path)
        print(f"✅ CONFIG SNAPSHOT: {yaml_path}")
        
    else:
        print(f"\n❌ FAILURE: No runs matched Target Hash '{target_id}'.")
        print("\n🔎 DIAGNOSIS: Here are the Experiment IDs found in your database:")
        if found_ids:
            for fid in found_ids:
                print(f"   - {fid}")
            print("\n👉 ACTION: If you see the ID above, your active.yaml is out of sync with the DB.")
            print("   Run 'python run_experiment.py ...' again to align them, OR re-run the Backfill.")
        else:
            print("   (No experiment_id metadata found at all. Did you Reload Definitions?)")

if __name__ == "__main__":
    extract_and_snapshot()