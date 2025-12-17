#!/bin/bash

# 1. SET THE ENVIRONMENT (No more manual exports)
export DAGSTER_HOME=$(pwd)
export PYTHONPATH=$PYTHONPATH:$(pwd)

# 2. ENSURE INFRASTRUCTURE IS UP
echo "🐘 Starting Postgres..."
docker-compose up -d

# 3. START DAGSTER DAEMON (Background)
# The daemon is what actually looks at dagster.yaml and enforces the limit=1
echo "🚦 Starting Dagster Daemon..."
dagster-daemon run & 
DAEMON_PID=$!

# 4. RUN YOUR EXPERIMENT
# We pass through all arguments ($@) so you can still use --auto
echo "🧬 Running Experiment Script..."
python run_experiment.py "$@"

# 5. CLEANUP
echo "🛑 Shutting down..."
kill $DAEMON_PID
# Optional: docker-compose down (Uncomment if you want to wipe DB after run)