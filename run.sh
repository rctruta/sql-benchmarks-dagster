#!/bin/bash
set -e  # Exit immediately if any command fails

# --- STEP 1: SET THE ENVIRONMENT ---
# This tells Dagster: "Look for dagster.yaml right here, not in the user's home folder."
export DAGSTER_HOME=$(pwd)
export PYTHONPATH=$PYTHONPATH:$(pwd)

echo "🤖 AGENT INITIALIZATION: Setting DAGSTER_HOME to $(pwd)"

# --- STEP 2: ENSURE INFRASTRUCTURE ---
# The Agent doesn't know if Docker is running. We ensure it is.
echo "🐘 AGENT: Starting Infrastructure..."
docker-compose up -d

# --- STEP 3: START THE COORDINATOR (The Daemon) ---
# The Daemon reads dagster.yaml and enforces the 'limit=1' rule.
# We run it in the background (&) so the script can continue.
echo "🚦 AGENT: Starting Traffic Control (Daemon)..."
mkdir -p data/dagster_home/storage # Ensure storage dir exists
dagster-daemon run > /dev/null 2>&1 &
DAEMON_PID=$!
echo "   -> Daemon started with PID $DAEMON_PID"

# Give the daemon a moment to wake up
sleep 3

# --- STEP 4: EXECUTE THE MISSION ---
# This runs your Python logic. The Agent doesn't need to know flags.
echo "🚀 AGENT: Launching Experiment..."
# Using --auto to tell your script "Don't ask for UI input, just run."
python run_experiment.py queue --auto

# --- STEP 5: CLEANUP ---
# When the mission is done, we kill the background daemon.
echo "🛑 AGENT: Mission Complete. Shutting down Daemon."
kill $DAEMON_PID