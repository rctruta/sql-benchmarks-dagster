from dagster import asset, AssetExecutionContext, MetadataValue, Output
from typing import List
import polars as pl
import json
import os

from ..constants import DATA_DIR, RESULTS_DIR
from ..utils.common import load_context
from ..partitions import partitions_def

STAGING_DIR = os.path.join(DATA_DIR, "staging")

CTX = load_context()

quality_assets: List[object] = []

def make_quality_asset(table_name):
    """
    Creates a validation asset for a specific table.
    Reads the staging Parquet file and verifies stats.
    """
    @asset(
        name=f"{table_name}_quality",
        group_name="data_generation",
        partitions_def=partitions_def,
        deps=[f"{table_name}_parquet"],
        description=f"Validates {table_name} distribution."
    )
    def _validate(context: AssetExecutionContext):
        partition_key = context.partition_key
        
        # Construct Path
        filename = f"{table_name}_{partition_key}.parquet"
        staging_file = os.path.join(STAGING_DIR, filename)
        
        if not os.path.exists(staging_file):
            raise FileNotFoundError(f"Staging file not found: {staging_file}")

        # Read Data
        df = pl.read_parquet(staging_file)
        row_count = df.height
        
        stats = {
            "rows": row_count,
            "columns": {}
        }
        
        # Compute Stats
        for col in df.columns:
            null_count = df[col].null_count()
            col_stats = {
                "null_count": null_count,
                "null_percent": null_count / row_count if row_count > 0 else 0,
                "cardinality": df[col].n_unique(),
                "dtype": str(df[col].dtype)
            }
            stats["columns"][col] = col_stats
            
        if row_count == 0:
             raise ValueError(f"Table {table_name} is empty!")

        # Save Profile to RESULTS Directory (Consolidation)
        # We need the Experiment ID to find the folder.
        # CTX is loaded globally, but for safety in the op we can reload or rely on CTX if it's dynamic enough.
        # Dagster context 'run_id' is dynamic, but 'experiment_id' is from env/config.
        # Best to reload context inside op if we think it changes per run, 
        # BUT 'make_quality_asset' is defined at import time. CTX global defaults are loaded then.
        # Let's trust CTX loaded at module level OR fetch from experiment config file if we needed 100% purity.
        # Given current architecture, CTX should be valid.
        
        exp_id = CTX['meta'].get("experiment_id", "unknown_exp")
        
        stats_dir = os.path.join(RESULTS_DIR, exp_id, "data_stats")
        os.makedirs(stats_dir, exist_ok=True)
        
        profile_path = os.path.join(stats_dir, f"{table_name}_{partition_key}.stats.json")
        
        with open(profile_path, "w") as f:
            json.dump(stats, f, indent=2)

        return Output(
            value=profile_path,
            metadata={
                "stats": MetadataValue.json(stats),
                "profile_path": MetadataValue.path(profile_path),
                "archive_location": MetadataValue.path(stats_dir)
            }
        )
    return _validate

# Generate for all tables
if CTX:
    for t in CTX.get('tables', []):
        quality_assets.append(make_quality_asset(t))
