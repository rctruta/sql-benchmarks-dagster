import pytest
import os
import json
from unittest.mock import patch, MagicMock
from sql_benchmarks.assets.reporting import parse_fragments_to_records
from sql_benchmarks.constants import RESULTS_DIR

# --- FIXTURES ---

@pytest.fixture
def mock_results_dir(tmpdir, monkeypatch):
    """Sets the RESULTS_DIR to a temporary directory for safe testing."""
    monkeypatch.setattr("sql_benchmarks.assets.reporting.RESULTS_DIR", str(tmpdir))
    return str(tmpdir)

def create_fragment(base_dir, exp_id, filename, content):
    """Helper to create a fragment file."""
    # Structure: base_dir / exp_id / fragments / filename
    fragment_dir = os.path.join(base_dir, exp_id, "fragments")
    os.makedirs(fragment_dir, exist_ok=True)
    
    path = os.path.join(fragment_dir, filename)
    with open(path, "w") as f:
        json.dump(content, f)
    return path

# --- TESTS ---

def test_parse_fragments_filters_by_id(mock_results_dir):
    """Only fragments matching the ID should be parsed."""
    target_id = "exp_A"
    
    # 1. Create Valid Fragment
    create_fragment(mock_results_dir, target_id, "frag1.json", {
        "meta": {"experiment_id": target_id, "asset": "bench_ssd", "engine": "duckdb"},
        "metrics": {"duration_seconds": 1.5},
        "parameters": {"rows": 100}
    })
    
    # 2. Create Invalid Fragment (Shouldn't exist in this folder structure theoretically, but logic checks meta)
    create_fragment(mock_results_dir, target_id, "frag_wrong_id.json", {
        "meta": {"experiment_id": "exp_B", "asset": "bench_ssd", "engine": "duckdb"}, # Mismatch
        "metrics": {}, 
        "parameters": {}
    })
    
    records = parse_fragments_to_records(target_id)
    assert len(records) == 1
    assert records[0]["Asset"] == "bench_ssd"

def test_parse_fragments_extracts_dimensions(mock_results_dir):
    """Verify metrics and dimensions are flattened correctly."""
    target_id = "exp_dims"
    
    create_fragment(mock_results_dir, target_id, "frag_full.json", {
        "meta": {"experiment_id": target_id, "asset": "bench_full", "engine": "postgres"},
        "metrics": {"duration_seconds": 120.5},
        "parameters": {
            "rows": 1000000,
            "derived_selectivity": 0.05,
            "disk_type": "ssd"
        }
    })
    
    records = parse_fragments_to_records(target_id)
    row = records[0]
    
    assert row["Rows"] == 1000000
    assert row["Selectivity"] == 0.05
    assert row["Duration"] == 120.5
    assert row["System"] == "postgres (ssd)" # Dynamic Construction

def test_parse_fragments_handles_corruption(mock_results_dir):
    """Corrupted JSON files should be skipped, not crash the pipeline."""
    target_id = "exp_corrupt"
    
    # Valid
    create_fragment(mock_results_dir, target_id, "valid.json", {
        "meta": {"experiment_id": target_id}, "metrics": {}, "parameters": {}
    })
    
    # Corrupt File
    f_path = os.path.join(mock_results_dir, target_id, "fragments", "garbage.json")
    with open(f_path, "w") as f:
        f.write("{ invalid json ...")
        
    records = parse_fragments_to_records(target_id)
    assert len(records) == 1 # Only the valid one survives
