
import sys
import os
import pytest
import subprocess

# TEST STRATEGY:
# We invoke execute_run.py as a SUBPROCESS with --dry-run.
# This proves:
# 1. The script is executable and importable.
# 2. Argument parsing works correctly (flags are recognized).
# 3. Logic branches are correctly selected based on flags.
# 4. It does not crash on import (e.g. invalid definitions).

EXEC_SCRIPT = [sys.executable, "execute_run.py"]

def test_cli_partition_dry_run():
    """Verify --partition flag triggers correct logic."""
    cmd = EXEC_SCRIPT + ["--partition", "test_part", "--dry-run"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    assert result.returncode == 0
    assert "[SDK] DRY-RUN: Success" in result.stdout
    # Verify partition was captured
    assert "Partition: test_part" in result.stdout
    # Verify correct selection was chosen logic-side (Group selection)
    assert "AssetSelection.groups(...)" in result.stdout

def test_cli_reporting_dry_run():
    """Verify --reporting flag selection."""
    cmd = EXEC_SCRIPT + ["--reporting", "--dry-run"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    assert result.returncode == 0
    assert "[SDK] DRY-RUN: Success" in result.stdout
    assert "AssetSelection.groups('reporting')" in result.stdout
    assert "Partition: None" in result.stdout

def test_cli_all_dry_run():
    """Verify --all flag selection."""
    cmd = EXEC_SCRIPT + ["--all", "--dry-run"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    assert result.returncode == 0
    assert "[SDK] DRY-RUN: Success" in result.stdout
    assert "AssetSelection.all()" in result.stdout

def test_cli_missing_args():
    """Verify script fails cleanly if no mode is provided."""
    cmd = EXEC_SCRIPT # No args
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    assert result.returncode != 0
    assert "Must specify" in result.stderr or "Must specify" in result.stdout

def test_cli_help():
    """Verify help menu works."""
    cmd = EXEC_SCRIPT + ["--help"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    assert result.returncode == 0
    assert "--dry-run" in result.stdout
    assert "--partition" in result.stdout
