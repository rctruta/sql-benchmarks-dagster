
import sys
import argparse
from dagster import AssetSelection
from sql_benchmarks.definitions import defs, all_assets
from sql_benchmarks.utils.common import load_context

def run_job(partition=None, reporting=False, run_all=False, dry_run=False):
    """
    Core logic to Execute the Dagster Job via SDK.
    Accessible by tests without CLI args.
    """
    if dry_run:
        print(f"[SDK] DRY-RUN: Would load job 'benchmark_job'")
        # Simulate definitions load checks but skip actual job loading
    else:
        # Access the pre-defined job from the Definitions object
        try:
            job = defs.get_job_def("benchmark_job")
        except Exception as e:
            print(f"[SDK] Error loading job execution definition: {e}")
            return False

    # Logic to select assets using the SDK
    if reporting:
        selection_desc = "AssetSelection.groups('reporting')"
        pk = None 
    elif run_all:
        selection_desc = "AssetSelection.all()"
        pk = None
    elif partition:
        selection_desc = "AssetSelection.groups(...)"
        pk = partition
    else:
        print("[ERROR] No valid execution mode selected.")
        return False

    print(f"[SDK] Executing job 'benchmark_job' with partition='{pk}'...")
    
    if dry_run:
        print(f"[SDK] DRY-RUN: Success. Selection: {selection_desc}, Partition: {pk}")
        return True

    # Real Execution Logic
    if reporting:
        selection = AssetSelection.groups("reporting")
    elif run_all:
        selection = AssetSelection.all()
    else:
        selection = AssetSelection.groups(
            "data_generation", 
            "ingestion", 
            "dynamic_bench_postgres", 
            "dynamic_bench_duckdb"
        )

    # RESOLVE SELECTION
    try:
        ctx = load_context()
        exp_id = ctx['meta'].get("experiment_id", "unknown")
        target_prefix = f"e_{exp_id}__"
        
        # Resolve Selection to List[AssetKey] as execute_in_process requires Sequence
        raw_keys = list(selection.resolve(all_assets))
        
        # Mandatory Scoping: Only run assets belonging to THIS experiment
        resolved_keys = [k for k in raw_keys if k.path[-1].startswith(target_prefix)]
        
        # Exception: Reporting assets might not be scoped or use a different convention
        if reporting:
            resolved_keys = raw_keys # Reporting is global for now or handles internal filtering
        
        if not resolved_keys:
            print("[SDK] Warning: Asset selection resolved to empty set.")
        
        result = job.execute_in_process(
            partition_key=pk,
            asset_selection=resolved_keys
        )

        if not result.success:
            print("[SDK] Job Failed.")
            return False
        
        print("[SDK] Job Success.")
        return True
        
    except Exception as e:
        print(f"[SDK] Exception during execution: {e}")
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--partition", type=str, help="Partition key to execute")
    parser.add_argument("--reporting", action="store_true", help="Run reporting assets only")
    parser.add_argument("--all", action="store_true", help="Run all assets unpartitioned")
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution")
    args = parser.parse_args()

    if not (args.partition or args.reporting or args.all):
        print("[ERROR] Must specify --partition, --reporting, or --all")
        sys.exit(1)

    success = run_job(args.partition, args.reporting, args.all, args.dry_run)
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
