#!/bin/bash

# Audit State Tool for Human Verification
# This script helps the human verify the codebase state after a security violation.

ROOT_DIR=$(pwd)
LOCK_FILE="$ROOT_DIR/audit.lock"

echo "--------------------------------------------------------"
echo "AGENT SAFETY AUDIT: System State Verification"
echo "--------------------------------------------------------"

if [ ! -f "$LOCK_FILE" ]; then
    echo "[OK] No active audit lock found."
else
    echo "[LOCKED] System is in 'Slow Protocol' Audit Mode."
fi

echo ""
echo "1. GIT STATUS (Core Drift)"
git status -s

echo ""
echo "2. DISK USAGE (Experiments & Data)"
du -sh sql_benchmarks/experiments/results sql_benchmarks/experiments/violations data 2>/dev/null

echo ""
echo "3. RECENT MODIFICATIONS (Last 5 mins)"
find . -maxdepth 4 -not -path '*/.*' -mmin -5 -type f

echo ""
echo "--------------------------------------------------------"
if [ -f "$LOCK_FILE" ]; then
    echo "If you have verified the state is safe, remove the lock to resume:"
    echo "  rm audit.lock"
    echo ""
    read -p "Would you like me to remove the lock for you now? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm "$LOCK_FILE"
        echo "[SUCCESS] Lock removed. Agent is now free to operate."
    fi
else
    echo "System is healthy. No action required."
fi
echo "--------------------------------------------------------"
