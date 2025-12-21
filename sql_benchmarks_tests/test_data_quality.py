import pytest
import os
import json
import polars as pl
from unittest.mock import MagicMock, patch
from dagster import build_asset_context, Output
from sql_benchmarks.assets.data_quality import make_quality_asset

@pytest.fixture
def mock_dirs(tmpdir, monkeypatch):
    """Mocks STAGING_DIR and RESULTS_DIR."""
    monkeypatch.setattr("sql_benchmarks.assets.data_quality.STAGING_DIR", str(tmpdir))
    monkeypatch.setattr("sql_benchmarks.assets.data_quality.RESULTS_DIR", str(tmpdir))
    return str(tmpdir)

def test_quality_asset_success(mock_dirs, monkeypatch):
    """Verifies that the asset correctly calculates stats and saves JSON."""
    table_name = "test_ok"
    partition = "defaults"
    exp_id = "test_exp"
    
    # 1. Create Mock Parquet
    df = pl.DataFrame({"a": [1, 2, None], "b": ["x", "y", "z"]})
    file_path = os.path.join(mock_dirs, f"{table_name}_{partition}.parquet")
    df.write_parquet(file_path)
    
    # 2. Build Asset & Context
    asset_factory = make_quality_asset(table_name)
    
    # Mock Context to provide experiment_id
    context = build_asset_context(
        partition_key=partition,
        resources={"io_manager": MagicMock()} 
    )

    # CTX is a global variable instantiated at import time.
    # Patching load_context doesn't update CTX if it's already loaded.
    # We must patch CTX directly.
    monkeypatch.setattr("sql_benchmarks.assets.data_quality.CTX", {"meta": {"experiment_id": exp_id}})
        
    # Run
    result = asset_factory(context)
    
    # 3. Assertions
    assert isinstance(result, Output)
    assert result.metadata["stats"] is not None
    
    # Verify JSON content in new location: RESULTS_DIR/exp_id/data_stats/...
    expected_stats_path = os.path.join(mock_dirs, exp_id, "data_stats", f"{table_name}_{partition}.stats.json")
    
    print(f"DEBUG: Mock Dirs: {mock_dirs}")
    print(f"DEBUG: Expected Path: {expected_stats_path}")
    if os.path.exists(mock_dirs):
        print(f"DEBUG: Root listing: {os.listdir(mock_dirs)}")
        exp_dir = os.path.join(mock_dirs, exp_id)
        if os.path.exists(exp_dir):
             print(f"DEBUG: Exp Dir listing: {os.listdir(exp_dir)}")
             stats_dir = os.path.join(exp_dir, "data_stats")
             if os.path.exists(stats_dir):
                 print(f"DEBUG: Stats Dir listing: {os.listdir(stats_dir)}")
             else:
                 print("DEBUG: Stats Dir not found")
        else:
             print(f"DEBUG: Exp Dir {exp_dir} not found")
             
    assert os.path.exists(expected_stats_path)
    
    with open(expected_stats_path) as f:
        stats = json.load(f)
        
    assert stats["rows"] == 3
    assert stats["columns"]["a"]["null_count"] == 1
    assert stats["columns"]["b"]["cardinality"] == 3

def test_quality_asset_fails_on_missing_file(mock_dirs):
    table_name = "test_missing"
    partition = "defaults"
    
    asset_factory = make_quality_asset(table_name)
    context = build_asset_context(partition_key=partition)
    
    with pytest.raises(FileNotFoundError):
        asset_factory(context)

def test_quality_asset_fails_on_empty_table(mock_dirs):
    table_name = "test_empty"
    partition = "defaults"
    
    # Write empty DF
    df = pl.DataFrame({"col1": []})
    file_path = os.path.join(mock_dirs, f"{table_name}_{partition}.parquet")
    df.write_parquet(file_path)
    
    asset_factory = make_quality_asset(table_name)
    context = build_asset_context(partition_key=partition)
    
    with pytest.raises(ValueError, match="is empty"):
        asset_factory(context)
