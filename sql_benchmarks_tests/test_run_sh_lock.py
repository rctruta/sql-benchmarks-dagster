
import re
import subprocess
import time
import os
import signal
import pytest
import shutil

RUN_SH_PATH = os.path.abspath("run.sh")
TEST_RUN_SH = os.path.abspath("run_test_mock.sh")
LOCK_FILE = "experiment.lock"

@pytest.fixture
def mock_run_sh():
    """Creates a modified run.sh that sleeps instead of running python."""
    with open(RUN_SH_PATH, "r") as f:
        content = f.read()
    
    # Replace the actual workload with a sleep command to simulate work,
    # keeping the lock logic intact — the lock is what's under test.
    #
    # Match the invocation by pattern, not by an exact literal. This fixture
    # used to hard-code the string 'python run_experiment.py "$@"'; when
    # run.sh changed the interpreter to "$PY", str.replace found nothing,
    # returned the content unchanged, and the tests silently executed the
    # REAL runner instead of sleeping. The failure surfaced as an argparse
    # usage error, which points nowhere near the actual cause.
    #
    # Both the pattern and the assertion below matter: a substitution that
    # can silently no-op is the bug, so a miss is now a loud error.
    mock_content, n = re.subn(
        r'^\s*(?:"?\$\{?PY\}?"?|python3?)\s+run_experiment\.py\s+"\$@"\s*$',
        "sleep 3",
        content,
        flags=re.MULTILINE,
    )
    assert n == 1, (
        f"mock fixture matched {n} run_experiment.py invocations in run.sh, expected 1. "
        "The workload line changed shape — update the pattern above, or this test "
        "would run the real experiment runner instead of a sleep."
    )

    # Disable daemon for the test to avoid starting real daemons
    mock_content, n_daemon = re.subn("dagster-daemon run", "echo 'Mock Daemon'", mock_content)
    assert n_daemon >= 1, "mock fixture found no dagster-daemon invocation to stub out"

    with open(TEST_RUN_SH, "w") as f:
        f.write(mock_content)
    
    os.chmod(TEST_RUN_SH, 0o755)
    
    # Cleanup previous lock if exists
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
        
    yield TEST_RUN_SH
    
    # Teardown
    if os.path.exists(TEST_RUN_SH):
        os.remove(TEST_RUN_SH)
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)

def test_concurrent_execution_blocked(mock_run_sh):
    """Verify that a second instance fails to start."""
    
    # 1. Start Process A (Runs for 3s)
    proc_a = subprocess.Popen([mock_run_sh], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    time.sleep(1.0) # Increase wait time to ensure it started
    
    if proc_a.poll() is not None:
        stdout, stderr = proc_a.communicate()
        print(f"Process A exited early! Ret code: {proc_a.returncode}")
        print(f"STDOUT: {stdout}")
        print(f"STDERR: {stderr}")
        pytest.fail("Process A exited before second instance could start")

    assert os.path.exists(LOCK_FILE), "Lock file should be created by Process A"
    
    # 2. Start Process B (Should fail immediately)
    result_b = subprocess.run([mock_run_sh], capture_output=True, text=True)
    
    assert result_b.returncode == 1, "Second instance should fail exit code 1"
    assert "Benchmark is already running" in result_b.stdout
    
    # 3. Wait for A to finish
    proc_a.wait()
    assert proc_a.returncode == 0
    
    # 4. Verify lock is cleared
    assert not os.path.exists(LOCK_FILE), "Lock file should be removed after A finishes"

def test_stale_lock_cleanup(mock_run_sh):
    """Verify that a stale lock (non-existent PID) is cleaned up."""
    
    # 1. Create a fake lock with a PID that definitely doesn't exist (e.g. 999999)
    # Note: On macOS/Linux PIDs wrap, but 999999 is usually safe for testing on standard kernels
    fake_pid = 999999
    with open(LOCK_FILE, "w") as f:
        f.write(str(fake_pid))
        
    # 2. Run script
    result = subprocess.run([mock_run_sh], capture_output=True, text=True)
    
    # 3. Should succeed
    assert result.returncode == 0
    assert "Found stale lock file" in result.stdout
    assert "Mock Daemon" in result.stdout or "sleep 3" in open(TEST_RUN_SH).read()
    
    # 4. Lock should be gone (cleanup trap)
    assert not os.path.exists(LOCK_FILE)

def test_lock_contains_correct_pid(mock_run_sh):
    """Verify the lock file actually contains the running PID."""
    proc = subprocess.Popen([mock_run_sh], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.5)
    
    with open(LOCK_FILE, 'r') as f:
        lock_pid = int(f.read().strip())
        
    assert lock_pid == proc.pid
    
    proc.wait()
