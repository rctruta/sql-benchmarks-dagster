import pytest
import os
import shutil
import tempfile
from sql_benchmarks.validator import ExperimentValidator
from sql_benchmarks.harness import IsolationHarness
from sql_benchmarks.constants import ROOT_DIR

def test_validator_negative_rows():
    """SHOWCASE: Rejects negative row counts."""
    bad_config = {
        "execution": {"engines": ["duckdb"], "matrix": {"rows": [-500]}}
    }
    with pytest.raises(ValueError) as excinfo:
        ExperimentValidator.validate(bad_config)
    assert "Negative value -500 not allowed" in str(excinfo.value)

def test_validator_selectivity_range():
    """SHOWCASE: Rejects selectivity out of bounds (0-1)."""
    bad_config = {
        "execution": {"engines": ["duckdb"], "matrix": {"selectivity": [1.5]}}
    }
    with pytest.raises(ValueError) as excinfo:
        ExperimentValidator.validate(bad_config)
    assert "Selectivity 1.5 for 'selectivity' must be between 0 and 1" in str(excinfo.value)

def test_harness_redirection_provisioning():
    """SHOWCASE: Verifies that the IsolationHarness correctly provisions the redirection environment."""
    harness = IsolationHarness("redirection_test")
    env = harness.provision()
    
    try:
        # Check that environment variables point to the scratchpad, NOT the repo
        assert env["SB_RESULTS_DIR"].startswith(harness.scratchpad_root), "RESULTS_DIR not redirected!"
        assert env["SB_DATA_DIR"].startswith(harness.scratchpad_root), "DATA_DIR not redirected!"
        
        # Verify scratchpad directories were actually created
        assert os.path.exists(env["SB_RESULTS_DIR"]), "Scratchpad results dir missing!"
        assert os.path.exists(os.path.join(env["SB_DATA_DIR"], "duckdb")), "Scratchpad duckdb dir missing!"
        
    finally:
        harness.cleanup()

def test_harness_isolation_integrity():
    """SHOWCASE: Verifies that the IsolationHarness monitor still protects the LIVE ROOT."""
    from sql_benchmarks.constants import PACKAGE_DIR
    poison_file = os.path.join(PACKAGE_DIR, "secure_pill.txt")
    with open(poison_file, "w") as f: f.write("Original")

    harness = IsolationHarness("integrity_test")
    harness.provision() # Snapshot of LIVE root taken here
    
    try:
        # ATTACK: Modify the LIVE ROOT while the "experiment" is running
        with open(poison_file, "w") as f: f.write("TAMPERED")
        
        drift = harness.check_integrity()
        assert any("MODIFIED" in d and "secure_pill.txt" in d for d in drift), "Failed to detect root tampering!"
        
    finally:
        if os.path.exists(poison_file): os.remove(poison_file)
        harness.cleanup()

def test_validator_broken_integrity():
    """SHOWCASE: Rejects experiments with broken foreign key relationships."""
    bad_fk_config = {
        "dataset": {
            "tables": {
                "orders": {
                    "columns": [
                        {"name": "cust_id", "provider": "foreign_key", "target_table": "customers"}
                    ]
                }
            }
        }
    }
    
    with pytest.raises(ValueError) as excinfo:
        ExperimentValidator.validate(bad_fk_config)
    
    assert "Broken FK in 'orders.cust_id'. Target table 'customers' not defined" in str(excinfo.value)
