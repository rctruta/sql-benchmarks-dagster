import polars as pl
import os
from dagster import MaterializeResult, MetadataValue

def generate(context, params, table_name, output_dir, dataset_config):
    partition_key = context.partition_key
    paths = dataset_config.get("paths", {})
    source_file = paths.get(table_name)
    
    if not source_file or not os.path.exists(source_file):
        raise FileNotFoundError(f"Missing file: {source_file}")

    context.log.info(f"Loading {source_file} via Polars...")

    # Polars Scan (Lazy Loading) -> Sink to Parquet
    # This effectively streams the data without loading it all into RAM.
    # It converts CSV to Parquet incredibly efficiently.
    
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{table_name}_{partition_key}.parquet")

    if source_file.endswith(".csv"):
        # scan_csv is lazy. sink_parquet executes it streaming.
        q = pl.scan_csv(source_file)
        q.sink_parquet(output_path)
        # To get row count for metadata, we do a quick count
        # (Or we can skip it if the file is massive)
        row_count = q.select(pl.len()).collect().item()
        
    elif source_file.endswith(".parquet"):
        # Direct copy (or scan/sink if we wanted to filter)
        # Using scan/sink ensures we normalize schema if needed
        q = pl.scan_parquet(source_file)
        q.sink_parquet(output_path)
        row_count = q.select(pl.len()).collect().item()

    return MaterializeResult(
        metadata={
            "path": MetadataValue.path(output_path),
            "row_count": MetadataValue.int(row_count),
            "engine": "polars_streaming"
        }
    )