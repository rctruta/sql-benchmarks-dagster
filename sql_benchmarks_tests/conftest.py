import pytest
import os
import yaml
from unittest.mock import patch, MagicMock
from sql_benchmarks.constants import EXPERIMENTS_DIR
from sql_benchmarks.resources.duckdb import DuckDBEngine

def load_real_config_and_shrink():
    """
    Reads the REAL baseline.yaml from the repo.
    Shrinks row counts and matrix dimensions so tests run in milliseconds.
    """
    # Prefer baseline.yaml (a stable, tracked reference) over active.yaml
    # (local runtime staging, gitignored). Fall back to archive/baseline.yaml
    # since baseline lives there in this repo. Fallback config used only if
    # nothing on disk.
    candidates = [
        os.path.join(EXPERIMENTS_DIR, "baseline.yaml"),
        os.path.join(EXPERIMENTS_DIR, "archive", "baseline.yaml"),
        os.path.join(EXPERIMENTS_DIR, "active.yaml"),
    ]
    source_path = next((p for p in candidates if os.path.exists(p)), None)
    
    if source_path is None:
        # Fallback only if NO config exists in the repo
        return get_fallback_config()

    with open(source_path, "r") as f:
        config = yaml.safe_load(f) or {}

    # A. Shrink Dataset
    if "dataset" in config and "tables" in config["dataset"]:
        for table_name, table_def in config["dataset"]["tables"].items():
            if isinstance(table_def.get("rows"), int):
                table_def["rows"] = 100


    # B. Shrink Execution Matrix
    if "execution" in config:

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
# Runs immediately. Reads YOUR file, Shrinks it, Writes it to active.yaml.
# The original content is preserved and restored at session end so running
# the suite never leaves active.yaml dirty in the working tree.
os.makedirs(EXPERIMENTS_DIR, exist_ok=True)
active_yaml_path = os.path.join(EXPERIMENTS_DIR, "active.yaml")

_original_active_yaml = None
if os.path.exists(active_yaml_path):
    with open(active_yaml_path, "r") as f:
        _original_active_yaml = f.read()

test_config = load_real_config_and_shrink()

with open(active_yaml_path, "w") as f:
    yaml.dump(test_config, f)


# Test files whose names contain any of these need external infra (Docker
# Postgres, the Quack server subprocess, remote Actian/TypeDB) and are auto-tagged
# `integration` so the default CI run (`-m "not integration"`) stays green without
# that infra. One place to maintain instead of decorating every file.
_INTEGRATION_FILE_MARKERS = ("postgres", "quack", "actian", "typedb", "runner_integration")


def pytest_collection_modifyitems(config, items):
    for item in items:
        fname = os.path.basename(str(getattr(item, "fspath", "")))
        if any(key in fname for key in _INTEGRATION_FILE_MARKERS):
            item.add_marker(pytest.mark.integration)


def pytest_sessionfinish(session, exitstatus):
    """Restore the pre-session active.yaml (it is runtime state, not ours to keep)."""
    if _original_active_yaml is not None:
        with open(active_yaml_path, "w") as f:
            f.write(_original_active_yaml)

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



BASE_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DATA_PATH = os.path.join(BASE_TEST_DIR, "fixtures", "test_hierarchy_small.parquet")

TEST_DATA_FOLDER = "/tmp/duckdb_data"
TEST_PARTITION_KEY = "medium_ssd"
TEST_TABLE_NAME = "test_table" 

@pytest.fixture
def static_parquet_path():
    """Provides the persistent, absolute path to the static Parquet fixture file."""
    if not os.path.exists(TEST_DATA_PATH):
        raise FileNotFoundError(f"CRITICAL: Static fixture file not found at: {TEST_DATA_PATH}. Please create it.")
    return TEST_DATA_PATH

@pytest.fixture # Default scope is function
def mock_duckdb_connect():
    """Globally mocks duckdb.connect used by DuckDBClient."""
    
    # We target the 'connect' function in the client module
    with patch("sql_benchmarks.resources.duckdb_client.duckdb.connect") as mock_connect_func:
        # Create a mock connection and result object
        mock_conn = MagicMock()
        mock_result = MagicMock()
        
        # Configure the result for typical read queries
        mock_result.fetchall.return_value = []
        
        # Configure the connection context manager to return the mock
        mock_connect_func.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value = mock_result
        
        yield mock_conn