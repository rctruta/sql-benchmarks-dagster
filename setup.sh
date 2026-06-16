#!/bin/bash
set -e

echo "--- SQL Benchmarking Laboratory: Environment Setup (uv) ---"

# 0. Require uv — the project's environment & dependency manager.
if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is required. Install it:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "  (see https://astral.sh/uv)"
    exit 1
fi

# 1. Create the virtual environment (uv fetches Python 3.11 automatically if needed)
if [ ! -d "venv" ]; then
    echo "[1/4] Creating virtual environment with uv (Python 3.11)..."
    uv venv venv --python 3.11 --prompt sqlbenchdag
else
    echo "[1/4] Virtual environment already exists."
fi

# 2. Install dependencies with uv
echo "[2/4] Installing dependencies with uv..."
uv pip install --python venv/bin/python -r requirements.txt

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
venv/bin/python -c "import dagster; import duckdb; import polars; print('  Core dependencies: OK')"
docker info > /dev/null 2>&1 && echo "  Docker: OK" || echo "  Docker: not found (Postgres/TypeDB engines unavailable; DuckDB quickstart still works)"

echo "--------------------------------------------------------"
echo "SETUP COMPLETE!"
echo "To start benchmarking:"
echo "  1. source venv/bin/activate"
echo "  2. Quick start (DuckDB only, no Docker required):"
echo "     ./run.sh sql_benchmarks/experiments/queue/quickstart.yaml --auto"
echo "  3. Full benchmark (requires Docker):"
echo "     ./run.sh queue --auto"
echo "--------------------------------------------------------"
