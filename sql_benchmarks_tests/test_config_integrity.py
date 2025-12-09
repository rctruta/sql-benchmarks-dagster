import pytest
import os
import yaml
import glob
from sql_benchmarks.constants import EXPERIMENTS_DIR
from sql_benchmarks.utils.schema import validate_yaml_content

# ==========================================
# 1. LOGIC VALIDATORS (Math & Integrity)
# ==========================================
# We keep these because Pydantic checks types, but not "Business Logic" 

def validate_stats(config, filename="<dict>"):
    """Checks that probabilities/weights are valid."""
    dataset = config.get("dataset", {})
    tables = dataset.get("tables", {})
    if not isinstance(tables, dict): return
    
    for table_name, table_def in tables.items():
        # Handle simple boolean cases (e.g. tpch: true)
        if not isinstance(table_def, dict): continue
        
        for col in table_def.get("columns", []):
            if "weights" in col:
                weights = col["weights"]
                assert min(weights) >= 0, f"Negative weight in {table_name}.{col['name']}"
                
                # Optional: Check sum is ~1.0
                total = sum(weights)
                if total <= 0:
                     pytest.fail(f"Weights sum to zero or less in {filename}")

def validate_integrity(config, filename="<dict>"):
    """Checks that Foreign Keys point to tables that actually exist."""
    dataset = config.get("dataset", {})
    tables = dataset.get("tables", {})
    if not isinstance(tables, dict): return

    defined_tables = set(tables.keys())
    
    for table_name, table_def in tables.items():
        if not isinstance(table_def, dict): continue
        
        for col in table_def.get("columns", []):
            if col.get("provider") == "foreign_key":
                target = col.get("target_table")
                assert target in defined_tables, \
                    f"Broken FK in '{table_name}'. Target '{target}' not defined in {filename}."

# ==========================================
# 2. THE TEST RUNNER
# ==========================================
from sql_benchmarks_tests.test_config_integrity import validate_stats, validate_integrity

yaml_files = glob.glob(os.path.join(EXPERIMENTS_DIR, "*.yaml"))
yaml_files += glob.glob(os.path.join(EXPERIMENTS_DIR, "queue", "*.yaml"))
yaml_files += glob.glob(os.path.join(EXPERIMENTS_DIR, "archive", "*.yaml"))

@pytest.mark.parametrize("filepath", yaml_files)
def test_repo_yaml_validity(filepath):
    """
    Validates every YAML file in the repo.
    """
    with open(filepath, "r") as f:
        config = yaml.safe_load(f)
        
    filename = os.path.basename(filepath)
    is_archive = "archive" in filepath

    # 1. SCHEMA VALIDATION (Strict V7 Contract)
    try:
        validate_yaml_content(config)
    except Exception as e:
        if is_archive:
            # LEGACY WAIVER: We don't force old experiments to match new schemas.
            # We just warn so we know they are effectively 'read-only' history.
            print(f"⚠️  Skipping strict schema check for legacy file: {filename}")
        else:
            # PRODUCTION ENFORCEMENT: Active/Queue files MUST be perfect.
            pytest.fail(f"Schema Validation Failed for {filename}:\n{e}")

    # 2. LOGIC VALIDATION (Universal Physics)
    # Even legacy files shouldn't have broken math or imaginary foreign keys.
    # If these fail, the experiment was scientifically invalid and should probably be deleted/fixed.
    validate_stats(config, filepath)
    validate_integrity(config, filepath)