import os
import yaml
import shutil
from dagster import sensor, RunRequest
from .jobs import benchmark_job
from .constants import EXPERIMENTS_DIR, ACTIVE_CONFIG_PATH
from .utils.common import generate_partition_keys

QUEUE_DIR = os.path.join(EXPERIMENTS_DIR, "queue")
ARCHIVE_DIR = os.path.join(EXPERIMENTS_DIR, "archive")

@sensor(job=benchmark_job, minimum_interval_seconds=5)
def experiment_queue_sensor(context):
    if not os.path.exists(QUEUE_DIR):
        return

    # 1. Scan for Files
# Cleaner Pythonic way
    files = sorted([f for f in os.listdir(QUEUE_DIR) if f.endswith((".yaml", ".yml"))])    
    for filename in files:
        filepath = os.path.join(QUEUE_DIR, filename)
        
        try:
            with open(filepath, "r") as f:
                config = yaml.safe_load(f)
        except Exception as e:
            context.log.warning(f"Skipping malformed file {filename}: {e}")
            continue

        # 2. Promote to Active
        context.log.info(f"Promoting {filename} to active configuration...")
        shutil.copy(filepath, ACTIVE_CONFIG_PATH)

        # 3. Calculate Partitions (Shared Logic)
        execution = config.get("execution", {})
        matrix = execution.get("matrix") or execution.get("dimensions")
        keys = generate_partition_keys(matrix)
        
        # 4. YIELD RUN REQUESTS
        if not keys:
            # Non-partitioned run
            yield RunRequest(run_key=f"run_{filename}", tags={"source": "agent"})
        else:
            # Partitioned: Yield one request per combination
            for pk in keys:
                yield RunRequest(
                    run_key=f"agent_{filename}_{pk}",
                    partition_key=pk,
                    tags={"source": "agent", "file": filename}
                )

        # 5. Archive
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        shutil.copy(filepath, os.path.join(ARCHIVE_DIR, filename))
        
        # Mark processed in queue so we don't loop forever
        new_name = filepath + ".processed"
        os.rename(filepath, new_name)
        
        return