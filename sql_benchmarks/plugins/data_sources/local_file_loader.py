import polars as pl
import os
from dagster import MaterializeResult, MetadataValue

def generate(context, params, table_name, output_dir, dataset_config):
    """
    Loads REAL data from a local path specified in the experiment YAML.
    """
    partition_key = context.partition_key
    
    paths = dataset_config.get("paths", {})
    source_file = paths.get(table_name)
    
    if not source_file:
        raise ValueError(f"CRITICAL: No path defined for table '{table_name}' in dataset.paths")
    
    if not os.path.exists(source_file):
        raise FileNotFoundError(f"CRITICAL: Real data file not found: {source_file}")

    context.log.info(f"Loading real data from {source_file}...")

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{table_name}_{partition_key}.parquet")

    if source_file.endswith(".csv"):
        # Streaming convert
        q = pl.scan_csv(source_file)
        q.sink_parquet(output_path)
        row_count = q.select(pl.len()).collect().item()
        
    elif source_file.endswith(".parquet"):
        q = pl.scan_parquet(source_file)
        q.sink_parquet(output_path)
        row_count = q.select(pl.len()).collect().item()
    else:
        raise ValueError("Unsupported file type. Use .csv or .parquet")

    return MaterializeResult(
        metadata={
            "path": MetadataValue.path(output_path),
            "row_count": MetadataValue.int(row_count),
            "source_file": MetadataValue.path(source_file),
            "loader_backend": "polars_streaming"
        }
    )