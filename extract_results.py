import pandas as pd
from dagster import DagsterInstance, DagsterEventType, DagsterRunStatus

def extract_benchmark_history():
    try:
        instance = DagsterInstance.get()
    except Exception:
        print("❌ CRITICAL: Could not find Dagster Instance.")
        print("Did you run 'export DAGSTER_HOME=~/.dagster'?")
        return

    print(f"DTO: Connected to Dagster storage at {instance.root_directory}")

    records = []
    
    # 1. Get the last 50 runs (The Brute Force approach)
    # This bypasses the flaky Asset Filter API entirely.
    runs = instance.get_runs(limit=50)
    print(f"Scanning {len(runs)} recent runs for benchmark data...")

    for run in runs:
        # Only look at successful runs to avoid noise
        if run.status != DagsterRunStatus.SUCCESS:
            continue

        # 2. Get all events for this run
        logs = instance.all_logs(run.run_id)
        
        for log in logs:
            # We only care about Asset Materializations
            if not log.is_dagster_event:
                continue
            if log.dagster_event.event_type != DagsterEventType.ASSET_MATERIALIZATION:
                continue
                
            # 3. Check if it's a benchmark asset
            # The asset key is stored in the event
            mat = log.dagster_event.step_materialization_data.materialization
            
            # Asset Key is a list of strings, e.g. ['duckdb_benchmark_join...']
            if not mat.asset_key:
                continue
                
            asset_name = mat.asset_key.path[-1]
            
            if "benchmark" not in asset_name:
                continue

            # 4. Extract Metadata
            meta = mat.metadata
            if "duration_seconds" not in meta:
                continue

            # Helper to safely get value
            def get_val(key):
                if key in meta:
                    return meta[key].value
                return None

            row = {
                "timestamp": pd.to_datetime(log.timestamp, unit='s'),
                "run_id": run.run_id,
                "asset": asset_name,
                # Use partition from the run tags if available, else from event
                "partition": run.tags.get("dagster/partition", "unknown"),
                "duration_seconds": get_val("duration_seconds"),
                "orphans": get_val("trace_orphans"),
                "rows": get_val("trace_rows"),
                "engine": get_val("config_engine")
            }
            
            # Engine Fallback
            if not row["engine"]:
                if "duckdb" in asset_name: row["engine"] = "duckdb"
                elif "pg_" in asset_name: row["engine"] = "postgres"

            records.append(row)

    # 5. Save
    if records:
        df = pd.DataFrame(records)
        df = df.sort_values(by=["engine", "rows", "orphans", "asset"])
        
        print("\n--- Extracted Results (Preview) ---")
        # Handle cases where orphans/rows might be None for older runs
        print(df[["asset", "rows", "orphans", "duration_seconds"]].head(10))
        
        filename = "benchmark_results_final.csv"
        df.to_csv(filename, index=False)
        print(f"\n✅ Saved {len(df)} records to {filename}")
    else:
        print("No benchmark metadata found in the last 50 runs.")

if __name__ == "__main__":
    extract_benchmark_history()