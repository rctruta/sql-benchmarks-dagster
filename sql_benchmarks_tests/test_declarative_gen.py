import pytest
import os
import shutil
import polars as pl
import numpy as np
from unittest.mock import MagicMock, patch

from sql_benchmarks.plugins.data_sources import declarative_gen
from sql_benchmarks.utils import providers
from sql_benchmarks.utils.schema import TableDef

# ==========================================
# 1. PROVIDER TESTS
# ==========================================
def test_provider_sequence():
    # Test Init
    res = providers.generate_sequence(rows=5)
    assert len(res) == 5
    assert np.all(res == [1, 2, 3, 4, 5])
    
    # Test Offset
    res_offset = providers.generate_sequence(rows=5, start=100)
    assert np.all(res_offset == [100, 101, 102, 103, 104])

def test_provider_choice():
    res = providers.generate_choice(rows=10, options=["A", "B"], weights=[0.5, 0.5])
    assert len(res) == 10
    assert set(res).issubset({"A", "B"})

def test_provider_choice_validation():
    with pytest.raises(ValueError):
        providers.generate_choice(rows=5, options=[])

def test_provider_foreign_key():
    # Foreign key should generate ints within range [1, rows]
    # (Since our implementation is simply random_int(1, rows+1))
    res = providers.generate_foreign_key(rows=100, table_name="test")
    assert len(res) == 100
    assert res.min() >= 1
    assert res.max() <= 100

def test_provider_text_concat():
    existing = {"id": [1, 2, 3]}
    res = providers.generate_text_concat(rows=3, existing_data=existing, source="id", prefix="key_")
    assert res == ["key_1", "key_2", "key_3"]

# ==========================================
# 2. GENERATOR INTEGRATION TESTS
# ==========================================
@pytest.fixture
def temp_output(tmp_path):
    return str(tmp_path / "output.parquet")

def test_declarative_gen_validation_missing_table(temp_output):
    config = {"tables": {}}
    with pytest.raises(ValueError, match="not defined in dataset config"):
        declarative_gen.generate({}, {}, "missing_table", temp_output, config)

def test_declarative_gen_validation_invalid_schema(temp_output):
    # Missing 'provider' in column def should raise Pydantic ValidationError
    config = {
        "tables": {
            "bad_table": {
                "rows": 10,
                "columns": [{"name": "col1"}] # Missing provider
            }
        }
    }
    with pytest.raises(Exception): # Pydantic ValidationError
        declarative_gen.generate({}, {}, "bad_table", temp_output, config)

def test_declarative_gen_success_flow(temp_output):
    config = {
        "tables": {
            "valid_table": {
                "rows": 10,
                "columns": [
                    {"name": "id", "provider": "sequence"},
                    {"name": "category", "provider": "choice", "options": ["X", "Y"], "weights": [0.1, 0.9]}
                ]
            }
        }
    }
    
    result = declarative_gen.generate({}, {}, "valid_table", temp_output, config)
    path = result.metadata["path"].value
    
    # Verify file exists and content is correct
    assert os.path.exists(path)
    df = pl.read_parquet(path)
    assert df.height == 10
    assert "id" in df.columns
    assert "category" in df.columns
    assert df["id"][0] == 1

def test_declarative_gen_foreign_key_flow(temp_output):
    config = {
        "tables": {
            "fk_table": {
                "rows": 50,
                "columns": [
                    {"name": "parent_id", "provider": "foreign_key", "target_table": "self", "target_column": "id"}
                ]
            }
        }
    }
    
    result = declarative_gen.generate({}, {}, "fk_table", temp_output, config)
    path = result.metadata["path"].value
    df = pl.read_parquet(path)
    assert df.height == 50
    assert df["parent_id"].min() >= 1

def test_declarative_gen_null_probability(temp_output):
    config = {
        "tables": {
            "null_table": {
                "rows": 1000,
                "columns": [
                    {
                        "name": "col_null", 
                        "provider": "sequence", 
                        "null_probability": 0.5
                    }
                ]
            }
        }
    }
    
    result = declarative_gen.generate({}, {}, "null_table", temp_output, config)
    path = result.metadata["path"].value
    df = pl.read_parquet(path)
    
    assert df.height == 1000
    null_count = df["col_null"].null_count()
    
    # 50% probability should yield roughly 500 nulls
    # Tolerating variance (e.g. 400-600)
    assert 400 < null_count < 600
    
    # Verify dtype is NOT Object (should be Int64 or similar)
    assert df["col_null"].dtype != pl.Object

def test_declarative_gen_variable_null_prob(temp_output):
    # Test matrix substitution for null_probability (string in config -> float in runtime)
    config = {
        "tables": {
            "test_table": {
                "rows": 100,
                "columns": [
                    {
                        "name": "col_a",
                        "provider": "sequence",
                        "null_probability": "p_var"
                    }
                ]
            }
        }
    }
    
    # Params dict simulating matrix expansion
    params = {"p_var": 0.5, "rows": 100}
    
    context = MagicMock() # Mock dagster context if needed, though generate() doesn't strict type check it
    
    result = declarative_gen.generate(context, params, "test_table", temp_output, config)
    path = result.metadata["path"].value
    
    df = pl.read_parquet(path)
    null_count = df["col_a"].null_count()
    # 40-60 range for 100 rows is valid
    assert 40 <= null_count <= 60
