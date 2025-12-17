#!/bin/bash

# 1. Set DAGSTER_HOME to the current directory (where dagster.yaml is)
export DAGSTER_HOME=$(pwd)

# 2. Ensure storage directory exists (so it doesn't complain)
mkdir -p data/dagster_home/storage

# 3. Start Dagster
echo "🚀 Starting Benchmark Platform with Local Config..."
dagster dev