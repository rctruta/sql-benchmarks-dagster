#!/bin/bash
set -e

echo "--- SQL Benchmarking Laboratory: Environment Setup ---"

# 1. Create Virtual Environment
if [ ! -d "venv" ]; then
    echo "[1/4] Creating virtual environment..."
    python3 -m venv venv
else
    echo "[1/4] Virtual environment already exists."
fi

# 2. Update Pip and Install Packages
echo "[2/4] Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Create Required Directories
echo "[3/4] Initializing filesystem..."
mkdir -p data/staging
mkdir -p data/duckdb
mkdir -p dagster_home
mkdir -p sql_benchmarks/experiments/queue
mkdir -p sql_benchmarks/experiments/archive
mkdir -p sql_benchmarks/experiments/results

# 4. Run Portability Audit
echo "[4/4] Running portability audit..."
python scripts/verify_portability.py

echo "--------------------------------------------------------"
echo "SETUP COMPLETE!"
echo "To start benchmarking:"
echo "  1. source venv/bin/activate"
echo "  2. ./run.sh queue --auto"
echo "--------------------------------------------------------"
