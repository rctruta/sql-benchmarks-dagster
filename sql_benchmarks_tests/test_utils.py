import pytest
from unittest.mock import patch, MagicMock
from sql_benchmarks.utils.common import (
    infer_metadata_from_sql, 
    normalize_distribution, 
    get_tables_used_in_sql,
    get_data_dependencies,
    load_context
)
from sql_benchmarks.utils.ddl import PostgresDDLGenerator
from sql_benchmarks.utils.system import thrash_os_cache
from sql_benchmarks.config_loader import ConfigLoader


# ==========================================
# 1. TEST THE "BRAIN" (Math & Metadata)
# ==========================================
def test_normalize_distribution_handles_ratios():
    options, weights = ["A", "B"], [1, 1]
    opts, probs = normalize_distribution(options, weights)
    assert probs[0] == 0.5

def test_infer_metadata_reads_sql_correctly():
    mock_config = {
        "tables": {
            "skewed_data": {
                "columns": [{
                    "name": "sel_code",
                    "options": ["sel_1", "sel_10", "filler"],
                    "weights": [0.01, 0.10, 0.89]
                }]
            }
        }
    }
    sql = "SELECT * FROM t WHERE col = 'sel_1';"
    meta = infer_metadata_from_sql(sql, mock_config)
    assert meta['selectivity_pct'] == 1.0

# ==========================================
# 2. TEST THE "PLUMBER" (Dependency Parsing)
# ==========================================
def test_get_tables_used_in_sql_parses_jinja():
    """Verify we find {{ table_name }} tags"""
    # Create a dummy SQL file
    with patch("builtins.open", new_callable=MagicMock) as mock_open:
        mock_file = MagicMock()
        mock_file.read.return_value = "SELECT * FROM {{ customers_table }} JOIN {{ orders_table }}"
        mock_open.return_value.__enter__.return_value = mock_file
        
        valid_tables = {"customers", "orders", "irrelevant"}
        used, _ = get_tables_used_in_sql("dummy.sql", valid_tables)
        
        assert "customers" in used
        assert "orders" in used
        assert "irrelevant" not in used

def test_get_data_dependencies_resolves_fks():
    """Verify upstream dependencies are found via Foreign Keys"""
    mock_configs = {
        "orders": {
            "columns": [
                {"name": "id"},
                {"name": "cust_id", "provider": "foreign_key", "target_table": "customers"}
            ]
        },
        "customers": {}
    }
    
    deps = get_data_dependencies("orders", mock_configs)
    assert "customers" in deps

# ==========================================
# 3. TEST THE "SYSTEM" (OS Cache)
# ==========================================

@patch("sql_benchmarks.utils.system.mmap")
@patch("sql_benchmarks.utils.system.psutil")
def test_thrash_os_cache_safety(mock_psutil, mock_mmap):
    """
    Verify safety logic. 
    Mocks a tiny computer (100MB RAM) so the test runs instantly.
    """
    # 1. Mock Tiny RAM (100 MB available)
    mock_mem = MagicMock()
    mock_mem.available = 100 * 1024 * 1024 
    mock_psutil.virtual_memory.return_value = mock_mem
    
    # 2. Ensure Silicon Safe is OFF for this test
    with patch.dict("os.environ", {"SB_SILICON_SAFE": "0"}):
        thrash_os_cache(override_gb=None)
    
    # Code uses min(available * 0.5, 4.0)
    expected_bytes = int(0.5 * 100 * 1024 * 1024)
    
    mock_mmap.mmap.assert_called()
    call_args = mock_mmap.mmap.call_args
    assert call_args[0][1] == expected_bytes
# ==========================================
# 4. TEST THE "ARCHITECT" (DDL)
# ==========================================
def test_ddl_pk_generation():
    table_def = {"columns": [{"name": "id", "primary_key": True}]}
    gen = PostgresDDLGenerator(table_def, "users_small", "small")
    assert "PRIMARY KEY (id)" in gen.generate_pk_sql()


def test_ddl_index_names_unique_per_partition():
    """Regression: a fixed config index name must not collide across partitions.
    Postgres index names are schema-global, but the same table_def is applied to
    every physical (per-partition) table — so the generated name must embed the
    physical table name, and must NOT use IF NOT EXISTS (which silently skipped
    all but the first partition's index)."""
    table_def = {"indexes": [{"name": "idx_sel", "columns": ["code"]}]}
    large = PostgresDDLGenerator(table_def, "skewed_data_large", "large").generate_index_sqls()
    medium = PostgresDDLGenerator(table_def, "skewed_data_medium", "medium").generate_index_sqls()
    assert large and medium
    assert large[0] != medium[0]                 # distinct names — no collision
    assert "IF NOT EXISTS" not in large[0]        # collisions must be loud
    assert "ON skewed_data_large" in large[0]

from sql_benchmarks.utils import common

MOCK_CONFIG_PAYLOAD = {
    "meta": {"experiment_id": "test_success"},
    "dataset": {
        "tables": {"orders": {}, "customers": {}}
    },
    "execution": {
        "engines": ["postgres", "duckdb"],
        "matrix": {"rows": ["small"], "disk_type": ["ssd"]},
    }
}

@pytest.fixture
def mock_compiler_setup(monkeypatch):
    """
    Uses monkeypatch to safely replace the global _GLOBAL_COMPILER
    with a mock object, using autospec to correctly capture instance attributes.
    """
    # 1. Create the Mock Object
    from sql_benchmarks.config_loader import ConfigLoader # Ensure access to the class

    # FIX: Use autospec=ConfigLoader for reliable attribute detection
    mock_compiler = MagicMock(autospec=ConfigLoader) 
    
    # 2. Setup the Mock's Properties (The Contract)
    # This setup will now work without the AttributeError
    mock_compiler.execution = MOCK_CONFIG_PAYLOAD['execution']
    mock_compiler.definitions = MOCK_CONFIG_PAYLOAD['definitions'] # <-- This line is now safe
    mock_compiler.dataset = MOCK_CONFIG_PAYLOAD['dataset']
    mock_compiler.get_full_config.return_value = MOCK_CONFIG_PAYLOAD
    
    # 3. Use monkeypatch to swap the global variable
    # ... rest of the fixture remains the same ...
    monkeypatch.setattr(common, "_GLOBAL_COMPILER", mock_compiler)
    
    yield mock_compiler