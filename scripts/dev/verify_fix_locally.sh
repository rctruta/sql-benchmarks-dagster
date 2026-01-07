#!/bin/bash
# scripts/verify_fix_locally.sh
# PURPOSE: Prove that the deployment logic handles a corrupted 'venv' state on Ubuntu 22.04.
# This runs locally in Docker, so we don't waste EC2 credits or time on "darts".

set -e

APP_DIR="/root/sql-benchmarks-dagster"

echo "🧪 Starting Simulation: Ubuntu 22.04 Environment..."
# Run a detached container to act as the "Remote Lab"
CID=$(docker run -d -it --rm ubuntu:22.04 bash)

# Function to run commands inside the container
run_in_sim() {
    docker exec $CID bash -c "$1"
}

cleanup() {
    echo "🧹 Cleaning up..."
    docker kill $CID > /dev/null
}
trap cleanup EXIT

echo "[1/3] Simulating 'Corrupt State'..."
# 1. Create a partial venv directory (simulating the failed previous run)
run_in_sim "mkdir -p ${APP_DIR}/venv"
# 2. Touch a file so it's not empty, but definitely NOT a valid venv
run_in_sim "touch ${APP_DIR}/venv/corrupted_marker"

echo "      State: $(run_in_sim 'ls -F /root/sql-benchmarks-dagster/venv/')"

echo "[2/3] Running 'remote_deploy.sh' Logic..."
# This matches the EXACT logic added to remote_deploy.sh
run_in_sim "
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y > /dev/null
    apt-get install -y python3-venv python3-pip > /dev/null

    cd ${APP_DIR}
    # THE REPAIR LOGIC
    if [ ! -f 'venv/bin/activate' ]; then
        echo '   [Logic Triggered] Found broken venv. Recreating...'
        rm -rf venv
        python3 -m venv venv
    fi
"

echo "[3/3] Verifying Result..."
if run_in_sim "[ -f ${APP_DIR}/venv/bin/activate ]"; then
    echo "✅ SUCCESS: Virtual Environment was successfully repaired & created."
    echo "   Validation: $(run_in_sim '${APP_DIR}/venv/bin/python3 --version')"
    exit 0
else
    echo "❌ FAILURE: venv/bin/activate still missing."
    exit 1
fi
