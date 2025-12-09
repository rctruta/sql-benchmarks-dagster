import os
import yaml
from dagster import sensor, RunRequest
from .jobs import benchmark_job
from .constants import EXPERIMENTS_DIR

QUEUE_DIR = os.path.join(EXPERIMENTS_DIR, "queue")

@sensor(job=benchmark_job, minimum_interval_seconds=5)
def experiment_queue_sensor(context):
    """
    The 'Agent Interface'.
    Watches /experiments/queue for new YAML files.
    When one appears, it validates it and triggers a run.
    """
    if not os.path.exists(QUEUE_DIR):
        return

    # 1. Scan for Files
    for filename in os.listdir(QUEUE_DIR):
        if not filename.endswith(".yaml"):
            continue

        filepath = os.path.join(QUEUE_DIR, filename)
        
        # 2. Safety Check (Validation)
        try:
            with open(filepath, "r") as f:
                config = yaml.safe_load(f)
            # Optional: Run your schema validation here if you want strict safety
            # validate_yaml_content(config) 
        except Exception as e:
            context.log.warning(f"Skipping malformed file {filename}: {e}")
            continue

        # 3. Trigger Run
        run_key = f"agent_run_{filename}"
        
        # Note: In a static partition system, the job runs the partitions 
        # defined at load time. Ideally, the Agent's YAML matches the 
        # active partitions (e.g. re-running a specific config).
        yield RunRequest(
            run_key=run_key,
            tags={"source": "agent", "file": filename}
        )
        
        # 4. Cleanup
        # In a real app, move the file to 'processed' so it doesn't trigger forever.
        # os.rename(filepath, os.path.join(EXPERIMENTS_DIR, "archive", filename))