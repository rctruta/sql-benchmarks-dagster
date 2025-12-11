import pytest
import os
import yaml
from sql_benchmarks.constants import EXPERIMENTS_DIR

def load_real_config_and_shrink():
    """
    Reads the REAL baseline.yaml from the repo.
    Shrinks row counts and matrix dimensions so tests run in milliseconds.
    """
    baseline_path = os.path.join(EXPERIMENTS_DIR, "baseline.yaml")
    active_path = os.path.join(EXPERIMENTS_DIR, "active.yaml")
    
    # 1. Load the best available Real Config
    source_path = baseline_path if os.path.exists(baseline_path) else active_path
    
    if os.path.exists(source_path):
        with open(source_path, "r") as f:
            config = yaml.safe_load(f) or {}
    else:
        # Fallback only if NO config exists in the repo
        return get_fallback_config()

    # 2. SHRINK IT (The "Safe Mode" Logic)
    # We keep the structure (keys, plugins, queries) but kill the volume.
    
    # A. Shrink Dataset
    if "dataset" in config and "tables" in config["dataset"]:
        for table_name, table_def in config["dataset"]["tables"].items():
            # If rows is a number, make it tiny
            if isinstance(table_def.get("rows"), int):
                table_def["rows"] = 100
            # If rows is a variable ("rows_var"), we handle it in the matrix below

    # B. Shrink Execution Matrix
    if "execution" in config:
        # Force the engine to just DuckDB (fastest for tests) if available
        # But keep user's list if they want to test postgres logic
        # config["execution"]["engines"] = ["duckdb"] 
        
        # Shrink the Matrix dimensions to 1 tiny option
        matrix = config["execution"].get("matrix") or config["execution"].get("dimensions") or {}
        
        # Overwrite specific scaling dimensions with tiny values
        if "rows" in matrix: matrix["rows"] = [100]
        if "size" in matrix: matrix["size"] = ["test_size"]
        
        # Ensure matrix is written back to V7 standard location
        config["execution"]["matrix"] = matrix

    return config

def get_fallback_config():
    """Only used if you deleted all your yaml files."""
    return {
        "meta": {"experiment_id": "fallback_test"},
        "dataset": {
            "source": "sql_benchmarks.plugins.data_sources.declarative_gen",
            "tables": {"t1": {"rows": 100, "columns": [{"name": "id", "provider": "sequence"}]}}
        },
        "execution": {
            "engines": ["duckdb"],
            "matrix": {"rows": [100]}
        }
    }

# --- GLOBAL SETUP ---
# Runs immediately. Reads YOUR file, Shrinks it, Writes it to active.yaml
os.makedirs(EXPERIMENTS_DIR, exist_ok=True)
active_yaml_path = os.path.join(EXPERIMENTS_DIR, "active.yaml")

test_config = load_real_config_and_shrink()

with open(active_yaml_path, "w") as f:
    yaml.dump(test_config, f)

@pytest.fixture(scope="session")
def test_context():
    return test_config

@pytest.fixture(scope="session")
def loaded_benchmark_assets():
    """
    Loads all assets dynamically within the fixture scope to ensure 
    partitions_def and other global state are fully initialized.
    """
    # Import the newly cleaned function
    from sql_benchmarks.assets.benchmark_factory import get_benchmark_assets 
    return get_benchmark_assets()