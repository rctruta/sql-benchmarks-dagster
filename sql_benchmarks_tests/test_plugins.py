import pytest
import shutil
import os
import polars as pl
from dagster import build_asset_context
from sql_benchmarks.plugins.data_sources.declarative_gen import generate

def test_synthetic_data_generation():
    """Verify the plugin creates a Parquet file with correct schema/rows"""
    output_dir = "/tmp/benchmark_test_data"
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Config Contract
    params = {"rows": 100}
    table_name = "test_users"
    dataset_config = {
        "tables": {
            "test_users": {
                "rows": "rows",
                "columns": [
                    {"name": "id", "provider": "sequence"},
                    {"name": "group", "provider": "choice", "options": ["A", "B"]}
                ]
            }
        }
    }

    # 2. Run Plugin
    context = build_asset_context(partition_key="small")
    result = generate(context, params, table_name, output_dir, dataset_config)
    
    # 3. Verify Output
    parquet_path = result.metadata["path"].value
    assert os.path.exists(parquet_path)
    
    df = pl.read_parquet(parquet_path)
    assert len(df) == 100
    assert "id" in df.columns
    assert "group" in df.columns
    
    # Cleanup
    shutil.rmtree(output_dir)