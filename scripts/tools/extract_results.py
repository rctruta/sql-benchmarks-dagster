import polars as pl
import yaml
import shutil
import os
import sys
from datetime import datetime
from dagster import DagsterInstance, DagsterEventType, DagsterRunStatus, RunsFilter

# STRICTLY FORCE THE LOCATION THAT WORKED IN DEBUG
os.environ["DAGSTER_HOME"] = os.path.expanduser("~/.dagster")

# Import your constants for file paths
from sql_benchmarks.constants import ACTIVE_CONFIG_PATH, CONFIG_ARCHIVE_DIR, RESULTS_DIR
from sql_benchmarks.assets.reporting import parse_fragments_to_records

def extract_and_snapshot():
    # 1. READ TARGET ID
    try:
        with open(ACTIVE_CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f)
        target_id = config.get("meta", {}).get("experiment_id")
        print(f"Target Experiment ID: {target_id}")
    except FileNotFoundError:
        print(f"Config not found at {ACTIVE_CONFIG_PATH}")
        return

    # 2. EXTRACT RECORDS (Via Shared Logic)
    print(f"Scanning fragments for experiment: {target_id}...")
    records = parse_fragments_to_records(target_id)
    
    # 3. SAVE RESULTS
    if records:
        df = pl.DataFrame(records)
        
        # Deduplicate to keep the latest run of each asset (Logic reused from reporting.py implicitly via output parity)
        df = df.unique(subset=["Asset", "System", "Rows"], keep="last").sort("Rows")
        
        # Define Paths
        result_dir = os.path.join(RESULTS_DIR, target_id)
        os.makedirs(result_dir, exist_ok=True)
        os.makedirs(CONFIG_ARCHIVE_DIR, exist_ok=True)

        csv_path = os.path.join(result_dir, f"results_{target_id}.csv")
        registry_path = os.path.join(CONFIG_ARCHIVE_DIR, f"config_{target_id}.yaml")
        
        # Write
        df.write_csv(csv_path)
        shutil.copy(ACTIVE_CONFIG_PATH, registry_path)

        print(f"\nSUCCESS!")
        print(f"   Extracted {len(df)} rows")
        print(f"   Saved to: {csv_path}")
    else:
        print(f"\nFAILURE: Scanned fragments but found 0 matches for ID '{target_id}'.")

if __name__ == "__main__":
    extract_and_snapshot()