import pytest
import os
import shutil
import polars as pl
import numpy as np
from unittest.mock import MagicMock, patch

from sql_benchmarks.plugins.data_sources import declarative_gen, providers
from sql_benchmarks.utils.schema import TableDef

# ==========================================
# 1. PROVIDER TESTS
# ==========================================
def test_provider_sequence():
    res = providers.generate_sequence(rows=5)
    assert len(res) == 5
    assert np.all(res == [1, 2, 3, 4, 5])

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
    
    path = declarative_gen.generate({}, {}, "valid_table", temp_output, config)
    
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
    
    path = declarative_gen.generate({}, {}, "fk_table", temp_output, config)
    df = pl.read_parquet(path)
    assert df.height == 50
    assert df["parent_id"].min() >= 1
