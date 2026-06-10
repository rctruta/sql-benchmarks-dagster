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


@patch("sql_benchmarks.utils.hasher.get_target_sql_dir")
def test_hasher_covers_all_measurement_relevant_code(mock_get_sql_dir, tmp_path):
    """
    The ID must change when engine code (resources/) or data generators
    (plugins/) change — not just assets/. Regression for the original
    boundary, where dcbd0bcc kept its ID across a quack_client change.
    """
    root = tmp_path
    sql_dir = root / "sql_benchmarks/scripts/sql/joins"
    os.makedirs(sql_dir, exist_ok=True)
    (sql_dir / "query.sql").write_text("SELECT 1;")
    mock_get_sql_dir.return_value = str(sql_dir)

    for code_dir in ("assets", "resources", "plugins"):
        os.makedirs(root / f"sql_benchmarks/{code_dir}", exist_ok=True)
        (root / f"sql_benchmarks/{code_dir}/mod.py").write_text("x = 1")

    config = {"execution": {"test_suite": "joins"}}
    baseline = generate_experiment_hash(config, str(root))

    for code_dir in ("assets", "resources", "plugins"):
        (root / f"sql_benchmarks/{code_dir}/mod.py").write_text(f"x = '{code_dir} changed'")
        new_hash = generate_experiment_hash(config, str(root))
        assert new_hash != baseline, f"{code_dir}/ change did not change the experiment ID"
        baseline = new_hash

    # Formatting-only change in resources/ must NOT change the ID
    # (AST normalization applies to all hashed code dirs equally).
    (root / "sql_benchmarks/resources/mod.py").write_text(
        "x   =   'resources changed'   # comment\n"
    )
    assert generate_experiment_hash(config, str(root)) == baseline


@patch("sql_benchmarks.utils.hasher.get_target_sql_dir")
def test_hasher_final_boundary_root_in_api_out(mock_get_sql_dir, tmp_path):
    """
    The ID fingerprints the QUESTION: package-root machinery (config_loader
    assembles engine_params) is inside the boundary; api/ only reads results
    and stays outside; experiments/ (configs+results churn) stays outside.
    """
    root = tmp_path
    sql_dir = root / "sql_benchmarks/scripts/sql/joins"
    os.makedirs(sql_dir, exist_ok=True)
    (sql_dir / "query.sql").write_text("SELECT 1;")
    mock_get_sql_dir.return_value = str(sql_dir)

    pkg = root / "sql_benchmarks"
    (pkg / "config_loader.py").write_text("x = 1")
    os.makedirs(pkg / "api", exist_ok=True)
    (pkg / "api/app.py").write_text("a = 1")
    os.makedirs(pkg / "experiments", exist_ok=True)
    (pkg / "experiments/gen.py").write_text("e = 1")

    config = {"execution": {"test_suite": "joins"}}
    baseline = generate_experiment_hash(config, str(root))

    # Root module change -> ID changes (this is where engine_params is assembled)
    (pkg / "config_loader.py").write_text("x = 'changed'")
    changed = generate_experiment_hash(config, str(root))
    assert changed != baseline, "config_loader.py change did not change the ID"

    # api/ and experiments/ changes -> ID must NOT change
    (pkg / "api/app.py").write_text("a = 'changed'")
    (pkg / "experiments/gen.py").write_text("e = 'changed'")
    assert generate_experiment_hash(config, str(root)) == changed


def test_capture_environment_records_conditions():
    """The capsule must record the bench: versions + hardware."""
    from sql_benchmarks.utils.system import capture_environment
    env = capture_environment()
    for key in ("python", "duckdb", "dagster", "os", "machine",
                "cpu_count_logical", "ram_total_gb"):
        assert key in env, f"environment block missing '{key}'"
    assert env["cpu_count_logical"] >= 1
    assert env["ram_total_gb"] > 0