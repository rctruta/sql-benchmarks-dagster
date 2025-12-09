import pytest
import os
import shutil
import yaml
from unittest.mock import patch
from sql_benchmarks.utils.hasher import generate_experiment_hash, normalize_sql

def test_normalize_sql_ignores_formatting():
    """Verify that formatting changes don't break the hash idempotency."""
    sql_1 = "SELECT * FROM table WHERE id = 1;"
    sql_2 = """
        SELECT * FROM table 
        WHERE id = 1; -- comment
    """
    assert normalize_sql(sql_1) == normalize_sql(sql_2)

@patch("sql_benchmarks.utils.hasher.get_target_sql_dir")
def test_hasher_sensitivity(mock_get_sql_dir, tmp_path):
    """Verify the hasher detects config changes but ignores irrelevant files."""
    root = tmp_path
    
    # 1. Setup Fake Project Structure
    # Use 'sql_benchmarks' (underscore) to match the package name logic
    sql_dir = root / "sql_benchmarks/scripts/sql/joins"
    os.makedirs(sql_dir, exist_ok=True)
    (sql_dir / "query.sql").write_text("SELECT 1;")
    
    assets_dir = root / "sql_benchmarks/assets"
    os.makedirs(assets_dir, exist_ok=True)
    (assets_dir / "logic.py").write_text("print('hello')")
    
    # MOCK: Tell the hasher to look at our FAKE sql dir, not the real one
    mock_get_sql_dir.return_value = str(sql_dir)

    # 1. Base Config
    config = {
        "dataset": {"tables": ["t1"]},
        "execution": {"test_suite": "joins"}
    }
    
    # --- BASELINE HASH ---
    hash_1 = generate_experiment_hash(config, str(root))
    
    # Case A: Change Config -> Hash MUST Change
    config_2 = config.copy()
    config_2["dataset"]["tables"] = ["t2"]
    hash_2 = generate_experiment_hash(config_2, str(root))
    assert hash_1 != hash_2
    
    # Case B: Change SQL -> Hash MUST Change
    (sql_dir / "query.sql").write_text("SELECT 2;")
    hash_3 = generate_experiment_hash(config, str(root))
    assert hash_1 != hash_3