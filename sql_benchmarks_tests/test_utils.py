import pytest
from unittest.mock import patch, MagicMock
from sql_benchmarks.utils.common import (
    infer_metadata_from_sql, 
    normalize_distribution, 
    get_tables_used_in_sql,
    get_data_dependencies
)
from sql_benchmarks.utils.ddl import PostgresDDLGenerator
from sql_benchmarks.utils.system import thrash_os_cache

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
    """Verify it calculates 75% RAM and calls mmap without crashing"""
    # Mock 10GB RAM
    mock_psutil.virtual_memory.return_value.total = 10 * 1024**3
    
    thrash_os_cache(override_gb=None)
    
    # Check Math: 10GB * 0.75 = 7.5GB
    expected_bytes = int(7.5 * 1024**3)
    
    # Verify mmap was called with correct size
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