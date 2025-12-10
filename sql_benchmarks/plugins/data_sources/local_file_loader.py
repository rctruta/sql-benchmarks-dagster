import polars as pl
import os
from dagster import MaterializeResult, MetadataValue

# CHANGED: 'output_dir' -> 'target_path'
def generate(context, params, table_name, target_path, dataset_config):
    """
    Normalizes REAL data (CSV/Parquet/JSON) into standard Parquet for the platform.
    """
    partition_key = context.partition_key
    
    # 1. GET PATH
    paths = dataset_config.get("paths", {})
    source_file = paths.get(table_name)
    
    if not source_file:
        raise ValueError(f"CRITICAL: No path defined for table '{table_name}' in dataset.paths")
    
    if not os.path.exists(source_file):
        raise FileNotFoundError(f"CRITICAL: Real data file not found: {source_file}")

    context.log.info(f"Normalizing real data from {source_file}...")

    # 2. STREAMING CONVERT (Lazy Evaluation)
    # Ensure directory exists
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    file_ext = os.path.splitext(source_file)[1].lower()

    try:
        # Create a LazyFrame (Scan) based on extension
        if file_ext == ".csv":
            q = pl.scan_csv(source_file, infer_schema_length=10000)
        elif file_ext == ".parquet":
            q = pl.scan_parquet(source_file)
        elif file_ext in [".json", ".ndjson"]:
            q = pl.scan_ndjson(source_file)
        else:
            raise ValueError(f"Unsupported file type: {file_ext}")

        # 3. SINK TO PARQUET
        # Use the explicit target_path provided by the factory
        q.sink_parquet(target_path)
        
        # 4. METADATA
        row_count = pl.scan_parquet(target_path).select(pl.len()).collect().item()
            
    except Exception as e:
        raise RuntimeError(f"Failed to process {source_file}: {e}")

    return MaterializeResult(
        metadata={
            "path": MetadataValue.path(target_path),
            "row_count": MetadataValue.int(row_count),
            "source_file": MetadataValue.path(source_file),
            "loader_backend": "polars_streaming"
        }
    )