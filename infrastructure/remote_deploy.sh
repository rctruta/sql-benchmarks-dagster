#!/bin/bash
# scripts/remote_deploy.sh
# Orchestrates the "Remote Intel Lab" experiment from your local machine.
# Usage: export REMOTE_LAB_IP="x.x.x.x"; ./scripts/remote_deploy.sh

# --- 1. CONFIGURATION ---
REMOTE_USER="ubuntu"
REMOTE_HOST="${REMOTE_LAB_IP}"
REMOTE_DIR="~/sql-benchmarks-dagster"
EXCLUDES=("--exclude=.git" "--exclude=__pycache__" "--exclude=data/*" "--exclude=experiments/results/*" "--exclude=venv")
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

if [ -z "$REMOTE_HOST" ]; then
    echo "[ERROR] REMOTE_LAB_IP is not set. Please export it: export REMOTE_LAB_IP='...'"
    exit 1
fi

echo "🚀 DEPLOYING TO REMOTE LAB: ${REMOTE_HOST}"

# --- 2. SYNC CODE (Local -> Remote) ---
echo "[1/4] Syncing Source Code..."
rsync -avz -e "ssh $SSH_OPTS" "${EXCLUDES[@]}" ./ ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}

# --- 3. PROVISION & EXECUTE (Remote) ---
echo "[2/4] Provisioning & Executing on Remote..."

# We pass a multi-line script to SSH
ssh $SSH_OPTS ${REMOTE_USER}@${REMOTE_HOST} "bash -s" <<-EOF
    set -e
    cd ${REMOTE_DIR}

    echo "   [Remote] Installing System Dependencies..."
    # Update and install venv/pip (requires sudo, default ubuntu user has passwordless sudo)
    sudo apt-get update -y
    sudo apt-get install -y python3-venv python3-pip docker-compose
    
    # Fix Docker Permissions for the ubuntu user
    sudo usermod -aG docker ubuntu

    echo "   [Remote] Checking Python Environment..."
    if [ ! -f "venv/bin/activate" ]; then
        echo "   [Remote] Creating/Recreating virtual environment..."
        rm -rf venv
        python3 -m venv venv
    fi
    source venv/bin/activate

    echo "   [Remote] Installing Dependencies..."
    pip install -r requirements.txt > /dev/null 2>&1

    echo "   [Remote] Starting Database Services..."
    # We installed docker-compose via apt, so it should be available. Force usage of .yaml and clean old .yml
    rm -f docker-compose.yml
    # Force re-run by clearing registry
    rm -rf sql_benchmarks/experiments/configs/config_*.yaml
    
    # --- ACTIAN MANUAL BUILD LOGIC ---
    # Find any uploaded Actian tarball and rename it to standard name
    if [ ! -f "/home/ubuntu/actian_installer.tgz" ]; then
        FOUND_TAR=$(find /home/ubuntu -maxdepth 1 -name "actian-vector*.tgz" | head -n 1)
        if [ -n "$FOUND_TAR" ]; then
            echo "   [Remote] Found uploaded installer: $FOUND_TAR"
            echo "   [Remote] Retargeting to 'actian_installer.tgz'..."
            mv "$FOUND_TAR" /home/ubuntu/actian_installer.tgz
        fi
    fi

    if [ -f "/home/ubuntu/actian_installer.tgz" ]; then
        echo "   [Remote] User provided Actian installer found. Preparing Docker build..."
        
        # Clone official repo if not already there
        if [ ! -d "Vector-Docker" ]; then
            git clone https://github.com/ActianCorp/Vector-Docker.git
        fi
        
        echo "   [Remote] Building 'local-actian:7.0' from source..."
        # Copy installer to build context
        cp /home/ubuntu/actian_installer.tgz Vector-Docker/
        
        # Build image
        cd Vector-Docker
        # Note: We must guess the build arg if the repo requires it, 
        # but usually simply having the file is enough for their 'ADD' instruction.
        # We will try a generic build.
        sudo docker build -t local-actian:7.0 .
        cd ..
    else
        echo "   [Remote] WARNING: 'actian_installer.tgz' not found in home dir."
        echo "   [Remote] Actian service will fail if image is missing."
    fi
    # ---------------------------------

    # Clean previous run
    sudo docker-compose -f docker-compose.yaml down --volumes --remove-orphans || true
    sudo docker-compose -f docker-compose.yaml up -d postgres actian

    echo "   [Remote] Waiting for Postgres..."
    # Wait for port 5432 to be open
    for i in {1..30}; do
        if sudo docker exec benchmark_postgres pg_isready -U postgres > /dev/null 2>&1; then
            echo "   [Remote] Postgres is ready!"
            break
        fi
        echo "   [Remote] Waiting for Postgres (attempt $i)..."
        sleep 2
    done

    echo "   [Remote] Waiting for Actian Vector..."
    # Wait for Actian to answer a simple query
    for i in {1..30}; do
        if sudo docker exec sql_bench_actian /opt/Actian/Vector/ingres/bin/iiquery -uactian -p benchmark_db -s <<<'select 1' > /dev/null 2>&1; then
            echo "   [Remote] Actian Vector is ready!"
            break
        fi
        echo "   [Remote] Waiting for Actian (attempt $i)..."
        sleep 5
    done
    
    # Debug: Print Actian logs if it failed to start
    echo "   [Remote] Actian Container Logs (Tail):"
    sudo docker logs --tail 20 sql_bench_actian || true


    echo "   [Remote] Executing Debug Baseline (Tiny)..."
    # Set safe mode for headless execution
    export SB_SILICON_SAFE=1
    python run_experiment.py sql_benchmarks/experiments/queue/debug_baseline.yaml --auto

EOF

# --- 4. RETRIEVE RESULTS (Remote -> Local) ---
echo "[4/4] Retrieving Results..."
mkdir -p sql_benchmarks/experiments/results
rsync -avz -e "ssh $SSH_OPTS" \
    ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/sql_benchmarks/experiments/results/ \
    ./sql_benchmarks/experiments/results/

echo "✅ REMOTE BENCHMARK COMPLETE."
echo "   Results: sql_benchmarks/experiments/results/results_debug_baseline.csv"
echo "   Report:  sql_benchmarks/experiments/results/dashboard_debug_baseline.html"
