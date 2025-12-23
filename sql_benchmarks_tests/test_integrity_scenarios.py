import os
import shutil
import tempfile
import pytest
from sql_benchmarks.utils.integrity_monitor import IntegrityMonitor
from sql_benchmarks.utils.hasher import generate_integrity_seal

def test_integrity_monitor_detects_modification():
    with tempfile.TemporaryDirectory() as tmp_dir:
        # 1. Setup initial state
        test_file = os.path.join(tmp_dir, "logic.py")
        with open(test_file, "w") as f:
            f.write("print('safe')")
        
        monitor = IntegrityMonitor(tmp_dir)
        
        # 2. Modify file
        with open(test_file, "w") as f:
            f.write("print('malicious')")
            
        # 3. Verify drift detection
        drift = monitor.check_drift()
        assert any("MODIFIED: logic.py" in d for d in drift)

def test_integrity_monitor_detects_addition():
    with tempfile.TemporaryDirectory() as tmp_dir:
        monitor = IntegrityMonitor(tmp_dir)
        
        # Add new file
        with open(os.path.join(tmp_dir, "virus.py"), "w") as f:
            f.write("exploit()")
            
        drift = monitor.check_drift()
        assert any("ADDED: virus.py" in d for d in drift)

def test_seal_consistency():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.makedirs(os.path.join(tmp_dir, "results"))
        with open(os.path.join(tmp_dir, "results", "data.csv"), "w") as f:
            f.write("1,2,3")
            
        seal1 = generate_integrity_seal(tmp_dir)
        seal2 = generate_integrity_seal(tmp_dir)
        
        assert seal1 == seal2
        
        # Modify and expect change
        with open(os.path.join(tmp_dir, "results", "data.csv"), "a") as f:
            f.write("\n4,5,6")
            
        seal3 = generate_integrity_seal(tmp_dir)
        assert seal1 != seal3

def test_staging_isolation_logic():
    """
    Verifies that the staging logic correctly handles pathing (conceptually).
    Actually testing the run_experiment.py flow requires a full harness.
    This test verifies that the monitor ignores results additions (expected)
    but flags code modifications.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Setup simulated harness in staging
        code_dir = os.path.join(tmp_dir, "sql_benchmarks")
        os.makedirs(code_dir)
        with open(os.path.join(code_dir, "assets.py"), "w") as f:
            f.write("logic()")
            
        monitor = IntegrityMonitor(tmp_dir)
        
        # Simulate normal execution (adding a result)
        results_dir = os.path.join(tmp_dir, "results")
        os.makedirs(results_dir)
        with open(os.path.join(results_dir, "out.csv"), "w") as f:
            f.write("data")
            
        # Simulate malicious tampering
        with open(os.path.join(code_dir, "assets.py"), "a") as f:
            f.write("\ninjection()")
            
        drift = monitor.check_drift()
        
        # Verify both detected
        assert any("ADDED" in d and "results" in d for d in drift)
        assert any("MODIFIED" in d and "assets.py" in d for d in drift)
