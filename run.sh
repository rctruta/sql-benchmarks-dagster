#!/bin/bash
set -e  # Exit immediately if any command fails

# Directory this script lives in, so the interpreter below resolves against
# the repo rather than the caller's CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- STEP 1: SINGLETON LOCK (Prevent Multiple Instances) ---
LOCKFILE="experiment.lock"

if [ -f "$LOCKFILE" ]; then
    PID=$(cat "$LOCKFILE")
    if ps -p "$PID" > /dev/null; then
        echo "[ERROR] Benchmark is already running (PID $PID)."
        exit 1
    else
        echo "[WARN] Found stale lock file (PID $PID). Cleaning up."
        rm -f "$LOCKFILE"
    fi
fi

echo $$ > "$LOCKFILE"

# --- STEP 2: SET THE ENVIRONMENT ---
export DAGSTER_HOME=$(pwd)/dagster_home
mkdir -p "$DAGSTER_HOME"
export PYTHONPATH=$PYTHONPATH:$(pwd)

echo "[INFO] Setting DAGSTER_HOME to $(pwd)/dagster_home"

# --- STEP 2: ENSURE INFRASTRUCTURE ---
# echo "[INFO] Starting Infrastructure..."
# docker-compose up -d
# NOTE: We now let postgres.py manage the container via docker-py SDK


# --- STEP 3: START THE COORDINATOR (The Daemon) ---
echo "[INFO] Checking Traffic Control (Daemon)..."

DAEMON_PID_FILE="dagster_daemon.pid"
MOUNTED_DAEMON=0

cleanup() {
    if [ "$MOUNTED_DAEMON" -eq 1 ]; then
        echo "[INFO] Mission Complete. Shutting down Daemon (PID $DAEMON_PID)."
        kill $DAEMON_PID 2>/dev/null || true
    else
        echo "[INFO] Leaving existing Daemon running."
    fi
    rm -f "experiment.lock"
}

# Trap cleanup on EXIT (success, fail, or interrupt)
trap cleanup EXIT

if pgrep -f "dagster-daemon run" > /dev/null; then
    echo "       -> Daemon is already running."
else
    echo "       -> Starting new Daemon..."
    dagster-daemon run > /dev/null 2>&1 &
    DAEMON_PID=$!
    MOUNTED_DAEMON=1
    echo "       -> Daemon started with PID $DAEMON_PID"
    sleep 3
fi

# --- STEP 4: EXECUTE THE MISSION ---
echo "[INFO] Launching Experiment Runner..."

# Pass all arguments provided to this script ($@) to the python script
# Example: ./run.sh queue --auto -> python run_experiment.py queue --auto
#
# Resolve the interpreter explicitly rather than calling a bare `python`.
# A bare `python` only resolves when a venv happens to be activated in the
# calling shell; macOS ships python3 only. Any caller that spawns this script
# without activation — including test_golden_capsule.py — got
# "python: command not found" and exit 127. Prefer the repo venv so the run
# uses the project's pinned deps regardless of how the shell was set up.
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    PY="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3 > /dev/null 2>&1; then
    PY="$(command -v python3)"
else
    echo "[ERROR] No usable interpreter: no $SCRIPT_DIR/.venv/bin/python and no python3 on PATH." >&2
    exit 1
fi

"$PY" run_experiment.py "$@"