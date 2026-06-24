from dagster import asset, AssetExecutionContext, MetadataValue, Output
from typing import List
import polars as pl
import json
import os

from ..constants import DATA_DIR, RESULTS_DIR
from ..utils.common import load_context, get_scoped_asset_name
from ..partitions import partitions_def

# Resolved inside assets to stay dynamic

CTX = load_context()
EXP_ID = CTX['meta'].get("experiment_id", "unknown")

quality_assets: List[object] = []

def make_quality_asset(table_name):
    """
    Creates a validation asset for a specific table.
    Reads the staging Parquet file and verifies stats.
    """
    scoped_name = get_scoped_asset_name(f"{table_name}_quality", EXP_ID)
    deps = [get_scoped_asset_name(f"{table_name}_parquet", EXP_ID)]

    @asset(
        name=scoped_name,
        group_name="data_generation",
        partitions_def=partitions_def,
        deps=deps,
        description=f"Validates {table_name} distribution."
    )
    def _validate(context: AssetExecutionContext):
        partition_key = context.partition_key
        
        # Resolve EXP_ID inside the function for dynamic behavior (essential for testing)
        ctx = load_context()
        current_exp_id = ctx['meta'].get("experiment_id", "unknown")
        
        # 2. LOAD DATA
        filename = f"{table_name}_{partition_key}.parquet"
        parquet_path = os.path.join(DATA_DIR, "staging", filename)
        
        if not os.path.exists(parquet_path):
            raise FileNotFoundError(f"Staging file not found: {parquet_path}")

        # Read Data
        df = pl.read_parquet(parquet_path)
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

        # Datagen↔stats contract: fail loudly if the generated data drifts from
        # what the config DECLARED (wrong dtype, wrong null rate, missing column)
        # — profiling alone silently records drift instead of catching it.
        # Skipped when no table_def is available (e.g. unit tests that stub
        # load_context); a contract can only be checked against a declaration.
        from ..utils.datagen_contract import verify_stats_against_config
        table_def = ctx.get("table_defs", {}).get(table_name)
        if table_def:
            violations, skipped = verify_stats_against_config(table_def, stats)
            if violations:
                raise ValueError(
                    f"Datagen contract violated for '{table_name}_{partition_key}': "
                    + "; ".join(violations)
                )
            if skipped:
                context.log.info(
                    f"Datagen contract for '{table_name}_{partition_key}': "
                    f"{len(skipped)} check(s) skipped (unverifiable): {skipped}"
                )

        # Results are isolated by current_exp_id in RESULTS_DIR
        target_path = os.path.join(RESULTS_DIR, current_exp_id, "data_stats", f"{table_name}_{partition_key}.stats.json")
        stats_dir = os.path.dirname(target_path)
        os.makedirs(stats_dir, exist_ok=True)
        
        with open(target_path, "w") as f:
            json.dump(stats, f, indent=2)

        return Output(
            value=target_path,
            metadata={
                "stats": MetadataValue.json(stats),
                "profile_path": MetadataValue.path(target_path),
                "archive_location": MetadataValue.path(stats_dir)
            }
        )
    return _validate

# Generate for all tables
if CTX:
    for t in CTX.get('tables', []):
        quality_assets.append(make_quality_asset(t))
