import polars as pl
import os
from dagster import MaterializeResult, MetadataValue

def generate(context, params, table_name, output_dir, dataset_config):
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
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{table_name}_{partition_key}.parquet")

    file_ext = os.path.splitext(source_file)[1].lower()

    try:
        # Create a LazyFrame (Scan) based on extension
        if file_ext == ".csv":
            # infer_schema_length=0 is dangerous for staging, 10000 is safer
            q = pl.scan_csv(source_file, infer_schema_length=10000)
        elif file_ext == ".parquet":
            q = pl.scan_parquet(source_file)
        elif file_ext in [".json", ".ndjson"]:
            # --- NEW CAPABILITY ---
            q = pl.scan_ndjson(source_file)
        else:
            raise ValueError(f"Unsupported file type: {file_ext}")

        # 3. SINK TO PARQUET
        # This streams the data, converting it to the platform's standard format
        q.sink_parquet(output_path)
        
        # 4. METADATA
        # Quick count from the resulting parquet file
        row_count = pl.scan_parquet(output_path).select(pl.len()).collect().item()
            
    except Exception as e:
        raise RuntimeError(f"Failed to process {source_file}: {e}")

    return MaterializeResult(
        metadata={
            "path": MetadataValue.path(output_path),
            "row_count": MetadataValue.int(row_count),
            "source_file": MetadataValue.path(source_file),
            "loader_backend": "polars_streaming"
        }
    )