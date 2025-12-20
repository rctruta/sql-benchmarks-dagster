import pytest
import os
import polars as pl
from dagster import build_asset_context
from sql_benchmarks.plugins.data_sources.local_file_loader import generate as gen_local
from sql_benchmarks.plugins.data_sources.tpc_h import generate as gen_tpch

def test_local_file_loader_normalization(tmp_path):
    """Verify we can ingest a random CSV and output standard Parquet."""
    # 1. Create Dummy Input
    input_csv = tmp_path / "raw_data.csv"
    input_csv.write_text("col1,col2\n1,A\n2,B")
    
    output_dir = str(tmp_path / "staging")
    
    # 2. Configure
    config = {
        "paths": {"my_table": str(input_csv)}
    }
    
    # 3. Run
    context = build_asset_context(partition_key="prod")
    full_path = os.path.join(output_dir, "my_table.parquet")
    result = gen_local(context, {}, "my_table", full_path, config)
    
    # 4. Verify
    out_file = result.metadata["path"].value
    df = pl.read_parquet(out_file)
    assert len(df) == 2
    assert "col1" in df.columns