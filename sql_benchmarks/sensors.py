import os
import yaml
import shutil
import itertools
from dagster import sensor, RunRequest
from .jobs import benchmark_job
from .constants import EXPERIMENTS_DIR, ACTIVE_CONFIG_PATH

QUEUE_DIR = os.path.join(EXPERIMENTS_DIR, "queue")

def _generate_keys(config):
    """
    Helper: Extracts partition keys from the YAML Matrix.
    Replicates the logic in your partitions.py
    """
    execution = config.get("execution", {})
    # Support both V6 (dimensions) and V7 (matrix) naming
    matrix = execution.get("matrix") or execution.get("dimensions")
    
    if not matrix:
        return []

    # 1. Extract dimensions (e.g. disk=[ssd], rows=[10000])
    keys = sorted(matrix.keys())
    values = [matrix[k] for k in keys]
    
    # 2. Cartesian Product
    partition_keys = []
    for combination in itertools.product(*values):
        # Join values with underscore: e.g. "ssd_100000"
        # We convert to string to be safe
        key_str = "_".join(str(v) for v in combination)
        partition_keys.append(key_str)
        
    return partition_keys

@sensor(job=benchmark_job, minimum_interval_seconds=5)
def experiment_queue_sensor(context):
    if not os.path.exists(QUEUE_DIR):
        return

    # 1. Scan for Files
    files = sorted([f for f in os.listdir(QUEUE_DIR) if f.endswith(".yaml")])
    
    for filename in files:
        filepath = os.path.join(QUEUE_DIR, filename)
        
        # 2. Load & Promote
        try:
            with open(filepath, "r") as f:
                config = yaml.safe_load(f)
        except Exception as e:
            context.log.warning(f"Skipping malformed file {filename}: {e}")
            continue

        context.log.info(f"Promoting {filename} to active configuration...")
        shutil.copy(filepath, ACTIVE_CONFIG_PATH)

        # 3. CALCULATE PARTITIONS
        keys = _generate_keys(config)
        
        if not keys:
            # Fallback for non-partitioned experiments?
            # Or log warning if partitions are expected.
            context.log.warning(f"No partitions found in {filename}. Triggering unpartitioned run.")
            yield RunRequest(run_key=f"run_{filename}", tags={"source": "agent"})
        else:
            # 4. YIELD ONE RUN PER PARTITION
            for pk in keys:
                run_key = f"agent_{filename}_{pk}"
                context.log.info(f"Requesting run for partition: {pk}")
                yield RunRequest(
                    run_key=run_key,
                    partition_key=pk,  # <--- THE FIX
                    tags={"source": "agent", "file": filename}
                )

        # 5. Archive
        archive_dir = os.path.join(EXPERIMENTS_DIR, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        shutil.move(filepath, os.path.join(archive_dir, filename))
        
        return