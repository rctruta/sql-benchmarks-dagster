import pandas as pd
import yaml
import shutil
import os
from dagster import DagsterInstance, DagsterRunStatus, DagsterEventType

def extract_and_snapshot():
    # 1. Read the YAML to find the current Experiment ID
    yaml_path = "sql_benchmarks/experiments.yaml"
    try:
        with open(yaml_path, "r") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print("❌ Could not find experiments.yaml")
        return
    
    # This is the key. We trust the YAML is the source of truth.
    target_id = config.get("meta", {}).get("experiment_id", "default")
    print(f"🎯 Target Experiment ID: {target_id}")

    # 2. Connect to Dagster
    try:
        instance = DagsterInstance.get()
    except Exception:
        print("❌ CRITICAL: Run 'export DAGSTER_HOME=~/.dagster'")
        return

    records = []
    
    # 3. Scan Runs (Brute force recent history)
    # We look for runs that MATCH the ID from the YAML
    runs = instance.get_runs(limit=100)
    print(f"Scanning {len(runs)} recent runs...")

    count = 0
    for run in runs:
        # Strict Tag Match: Only get runs that belong to this experiment
        if run.tags.get("experiment") != target_id:
            continue
            
        if run.status != DagsterRunStatus.SUCCESS:
            continue

        count += 1
        logs = instance.all_logs(run.run_id)
        
        for log in logs:
            if not log.is_dagster_event or log.dagster_event.event_type != DagsterEventType.ASSET_MATERIALIZATION:
                continue
            
            mat = log.dagster_event.step_materialization_data.materialization
            if not mat.asset_key: continue
            
            asset_name = mat.asset_key.path[-1]
            if "benchmark" not in asset_name: continue

            meta = mat.metadata
            if "duration_seconds" not in meta: continue

            def get_val(key): return meta[key].value if key in meta else None

            row = {
                "timestamp": pd.to_datetime(log.timestamp, unit='s'),
                "experiment_id": target_id, # Validated
                "asset": asset_name,
                "partition": run.tags.get("dagster/partition", "unknown"),
                "duration_seconds": get_val("duration_seconds"),
                "orphans": get_val("trace_orphans"),
                "rows": get_val("trace_rows"),
                "engine": get_val("config_engine")
            }
            if not row["engine"]:
                if "duckdb" in asset_name: row["engine"] = "duckdb"
                elif "pg_" in asset_name: row["engine"] = "postgres"

            records.append(row)

    # 4. Save Matched Artifacts
    if records:
        df = pd.DataFrame(records)
        df = df.sort_values(by=["engine", "rows", "orphans", "asset"])
        
        # Define Filenames based on the ID
        csv_name = f"results_{target_id}.csv"
        yaml_snapshot_name = f"config_{target_id}.yaml"
        
        # Save CSV
        df.to_csv(csv_name, index=False)
        print(f"\n✅ DATA SAVED: {csv_name}")
        
        # SNAPSHOT THE CONFIG
        shutil.copy(yaml_path, yaml_snapshot_name)
        print(f"📸 CONFIG SAVED: {yaml_snapshot_name}")
        print("   (These two files are now permanently linked)")
        
    else:
        print(f"⚠️  No runs found with tag 'experiment: {target_id}'.")
        print("Did you reload definitions and run the Backfill *after* updating the YAML?")

if __name__ == "__main__":
    extract_and_snapshot()