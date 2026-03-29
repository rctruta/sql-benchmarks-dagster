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

# 4. Verify environment
echo "[4/4] Verifying environment..."
python3 -c "import dagster; import duckdb; import polars; print('  Core dependencies: OK')"
docker info > /dev/null 2>&1 && echo "  Docker: OK" || echo "  Docker: not found (Postgres engine will be unavailable)"

echo "--------------------------------------------------------"
echo "SETUP COMPLETE!"
echo "To start benchmarking:"
echo "  1. source venv/bin/activate"
echo "  2. Quick start (DuckDB only, no Docker required):"
echo "     ./run.sh sql_benchmarks/experiments/queue/quickstart.yaml --auto"
echo "  3. Full benchmark (requires Docker):"
echo "     ./run.sh queue --auto"
echo "--------------------------------------------------------"
