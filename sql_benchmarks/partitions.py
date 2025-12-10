import os
import yaml
import itertools
from dagster import StaticPartitionsDefinition
from .constants import EXPERIMENTS_DIR

def build_partitions():
    """
    Builds partitions STRICTLY from the 'matrix' section of active.yaml.
    Engines are NOT part of the partition key.
    """
    config_path = os.path.join(EXPERIMENTS_DIR, "active.yaml")
    
    # 1. STRICT VALIDATION
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"CRITICAL: Config not found at {config_path}")

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
    except Exception as e:
        raise RuntimeError(f"CRITICAL: Failed to parse active.yaml: {e}")

    execution = config.get("execution", {})
    matrix = execution.get("matrix", {})

    # 2. FAIL FAST if Matrix is missing
    # Partitions are governed ONLY by the matrix. No matrix = No partitions.
    if not matrix:
        raise ValueError("CRITICAL: active.yaml missing 'execution.matrix'. Cannot generate partitions.")

    # 3. GENERATE MATRIX KEYS
    # We sort keys to ensure consistent naming (e.g., rows_disk)
    keys = sorted(matrix.keys())
    value_lists = [matrix[k] for k in keys]
    
    scenarios = []
    params_map = {}

    for combination in itertools.product(*value_lists):
        # Name: "10000_ssd" 
        # (This is a pure data slice. No engine info here.)
        name = "_".join(str(x) for x in combination)
        
        # Params: {'rows': 10000, 'disk_type': 'ssd'}
        params = dict(zip(keys, combination))
        
        scenarios.append(name)
        params_map[name] = params

    # 4. CREATE DEFINITION (1D List of Data Scenarios)
    partitions_def = StaticPartitionsDefinition(scenarios)

    return partitions_def, params_map

# --- EXPORTS ---
partitions_def, SCENARIO_CONFIG = build_partitions()

def get_params_for_partition(partition_key):
    """
    Decodes the partition key into the configuration for that data slice.
    """
    if partition_key not in SCENARIO_CONFIG:
        raise KeyError(f"Partition '{partition_key}' not found in configuration map.")
        
    matrix_params = SCENARIO_CONFIG[partition_key].copy()
    
    return {
        "SCENARIO_CONFIG": matrix_params
    }