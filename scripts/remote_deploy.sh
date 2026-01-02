#!/bin/bash
# scripts/remote_deploy.sh
# Orchestrates the "Remote Intel Lab" experiment from your local machine.

# --- 1. CONFIGURATION ---
REMOTE_USER="ubuntu"
REMOTE_HOST="${REMOTE_LAB_IP}" # Set this in your environment or replace with IP
REMOTE_DIR="~/sql-benchmarks-dagster"
EXCLUDES=("--exclude=.git" "--exclude=__pycache__" "--exclude=data/*" "--exclude=experiments/results/*")

if [ -z "$REMOTE_HOST" ]; then
    echo "[ERROR] REMOTE_LAB_IP is not set. Please export it or edit this script."
    exit 1
fi

echo "🚀 COMPILING REMOTE LAB: ${REMOTE_HOST}"

# --- 2. SYNC CODE (Local -> Remote) ---
echo "[1/4] Syncing Source Code..."
rsync -avz "${EXCLUDES[@]}" ./ ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}

# --- 3. PROVISION (Remote) ---
echo "[2/4] Provisioning Containers on Remote..."
ssh ${REMOTE_USER}@${REMOTE_HOST} "cd ${REMOTE_DIR} && docker-compose up -d"

# --- 4. EXECUTE (Remote) ---
echo "[3/4] Executing Competitive Baseline..."
# We use the --auto flag for non-interactive remote runs
ssh ${REMOTE_USER}@${REMOTE_HOST} "cd ${REMOTE_DIR} && python run_experiment.py sql_benchmarks/experiments/queue/competitive_baseline.yaml --auto"

# --- 5. RETRIEVE RESULTS (Remote -> Local) ---
echo "[4/4] Retrieving Results..."
rsync -avz --include="experiments/results/***" --exclude="*" ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/ ./

echo "✅ REMOTE BENCHMARK COMPLETE. Check your local experiments/results/ folder."
