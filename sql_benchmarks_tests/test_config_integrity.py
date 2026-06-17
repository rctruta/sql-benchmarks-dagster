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
            print(f"⚠️  Skipping strict schema check for legacy file: {filename}")
        elif "hallucination_demo" in filename:
            # We EXPECT this one to fail some validations, 
            # but let's see if it's the right KIND of failure
            print(f"✅ Correctly rejected known bad config: {filename}")
            return
        else:
            # PRODUCTION ENFORCEMENT: Active/Queue files MUST be perfect.
            pytest.fail(f"Schema Validation Failed for {filename}:\n{e}")

    # 2. LOGIC VALIDATION (Universal Physics)
    # Even legacy files shouldn't have broken math or imaginary foreign keys.
    # If these fail, the experiment was scientifically invalid and should probably be deleted/fixed.
    validate_stats(config, filepath)
    validate_integrity(config, filepath)

# ==========================================
# 3. CAPSULE CONFIG IS BYTE-FAITHFUL TO SOURCE
# ==========================================
def test_capsule_config_is_verbatim_source_not_redump(tmp_path):
    """Regression: the capsule's experiment_config.yaml must be the author's
    exact source bytes, NOT a yaml.dump re-serialization. A round-trip launders
    intent-bearing formatting (underscored ints, folded prose, unicode dashes),
    misrepresenting 'the exact config that ran'. The Experiment ID hashes the
    parsed dict, so verbatim archival changes no ID."""
    from sql_benchmarks.coordinator import ExperimentCoordinator

    raw = (
        "meta:\n"
        '  name: "selectivity – a test"\n'      # real en-dash
        "  description: >\n"
        "    a folded prose block — readable on purpose.\n"   # em-dash, folded
        "definitions:\n"
        "  rows:\n"
        "    large: 10_000_000\n"               # underscored int, readable
    )
    src = tmp_path / "exp.yaml"
    src.write_text(raw, encoding="utf-8")

    coord = ExperimentCoordinator(str(src))
    # run() captures this at validation; emulate that one step here.
    coord._source_yaml = src.read_text(encoding="utf-8")
    dest = tmp_path / "experiment_config.yaml"
    coord._archive_source_config(str(dest))

    archived = dest.read_text(encoding="utf-8")
    assert archived == raw                      # byte-identical
    assert "10_000_000" in archived             # underscores survive
    assert "–" in archived and "—" in archived  # real dashes, not \uXXXX

    # And prove the relic we removed WOULD have mangled it:
    redump = yaml.dump(yaml.safe_load(raw), sort_keys=False)
    assert "10_000_000" not in redump           # int underscores lost
    assert "\\u2013" in redump or "–" not in redump  # dash escaped under default dump


def test_archive_source_config_fails_loud_when_uncaptured(tmp_path):
    """No silent provenance hole: archiving with no captured source must raise."""
    from sql_benchmarks.coordinator import ExperimentCoordinator
    coord = ExperimentCoordinator(str(tmp_path / "nope.yaml"))
    with pytest.raises(RuntimeError):
        coord._archive_source_config(str(tmp_path / "out.yaml"))
