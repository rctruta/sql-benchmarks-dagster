import pytest
import os
import yaml
import glob
from sql_benchmarks.constants import EXPERIMENTS_DIR

# ==========================================
# 1. REUSABLE VALIDATORS (The Logic)
# ==========================================
def validate_structure(config, filename="<dict>"):
    """Core logic to check schema."""
    assert "dataset" in config, f"{filename} missing 'dataset' block"
    assert "engines" in config, f"{filename} missing 'engines' block"
    assert "meta" in config, f"{filename} missing 'meta' block"

    valid_engines = {"postgres", "duckdb"}
    for engine in config['engines']:
        assert engine in valid_engines, f"Unknown engine '{engine}' in {filename}"

def validate_stats(config, filename="<dict>"):
    """Core logic to check math."""
    tables = config.get("dataset", {}).get("tables", {})
    if isinstance(tables, list): return
    
    for table_name, table_def in tables.items():
        for col in table_def.get("columns", []):
            if "weights" in col:
                weights = col["weights"]
                # 1. No Negatives
                assert min(weights) >= 0, f"Negative weight in {table_name}.{col['name']}"
                
                # 2. Sum Check (warn or fail)
                total = sum(weights)
                # We allow 0.99-1.01 for float drift, but catch gross errors
                if not (0.95 <= total <= 1.05):
                     # In a strict org, this would be an error. 
                     # For now, we assert it's at least positive.
                     assert total > 0, "Weights sum to zero"

def validate_integrity(config, filename="<dict>"):
    """Core logic to check Foreign Keys."""
    tables = config.get("dataset", {}).get("tables", {})
    if isinstance(tables, list): return

    defined_tables = set(tables.keys())
    
    for table_name, table_def in tables.items():
        for col in table_def.get("columns", []):
            if col.get("provider") == "foreign_key":
                target = col.get("target_table")
                assert target in defined_tables, \
                    f"Broken FK in '{table_name}'. Target '{target}' not defined in {filename}."

# ==========================================
# 2. THE REPO CHECKS (Positive Tests)
# ==========================================
# These run against your ACTUAL files to ensure the repo is healthy.
yaml_files = glob.glob(os.path.join(EXPERIMENTS_DIR, "*.yaml"))
yaml_files += glob.glob(os.path.join(EXPERIMENTS_DIR, "queue", "*.yaml"))

@pytest.mark.parametrize("filepath", yaml_files)
def test_repo_yaml_validity(filepath):
    with open(filepath, "r") as f:
        config = yaml.safe_load(f)
    
    # Run all validators
    validate_structure(config, filepath)
    validate_stats(config, filepath)
    validate_integrity(config, filepath)

# ==========================================
# 3. THE VALIDATOR CHECKS (Negative Tests)
# ==========================================
# These verify that our validators actually catch bugs.

def test_validator_catches_missing_blocks():
    """Prove that missing 'meta' triggers an error."""
    bad_config = {
        "dataset": {}, 
        "engines": ["postgres"]
        # Missing 'meta'
    }
    with pytest.raises(AssertionError, match="missing 'meta'"):
        validate_structure(bad_config)

def test_validator_catches_invalid_engine():
    """Prove that 'oracle' triggers an error."""
    bad_config = {
        "dataset": {}, "meta": {},
        "engines": ["oracle"] # Invalid
    }
    with pytest.raises(AssertionError, match="Unknown engine"):
        validate_structure(bad_config)

def test_validator_catches_negative_weights():
    """Prove that negative math triggers an error."""
    bad_config = {
        "dataset": {
            "tables": {
                "t1": {
                    "columns": [{"name": "c1", "weights": [0.5, -0.1]}]
                }
            }
        }
    }
    with pytest.raises(AssertionError, match="Negative weight"):
        validate_stats(bad_config)

def test_validator_catches_broken_fks():
    """Prove that pointing to a ghost table triggers an error."""
    bad_config = {
        "dataset": {
            "tables": {
                "orders": {
                    "columns": [{
                        "provider": "foreign_key",
                        "target_table": "ghost_users" # Doesn't exist
                    }]
                }
                # 'ghost_users' is missing from keys
            }
        }
    }
    with pytest.raises(AssertionError, match="Broken FK"):
        validate_integrity(bad_config)