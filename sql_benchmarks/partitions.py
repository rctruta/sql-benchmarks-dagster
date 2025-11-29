import yaml
import itertools
import os
from dagster import StaticPartitionsDefinition

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "experiments")
ACTIVE_CONFIG_PATH = os.path.join(CONFIG_DIR, "active.yaml")

if not os.path.exists(ACTIVE_CONFIG_PATH):
    raise FileNotFoundError("⚠️ No active experiment. Run 'python run_experiment.py <file>'")

with open(ACTIVE_CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)

# 1. EXPORT METADATA
# This allows factories to import EXPERIMENT_META
EXPERIMENT_META = config.get("meta", {"experiment_id": "default"})

# Unpack Logic
defs = config["definitions"]
dims = config["dimensions"]
exclusions = config.get("exclude", [])

keys = list(dims.keys())
values = list(dims.values())
all_combinations = list(itertools.product(*values))

SCENARIO_CONFIG = {}
partition_keys = []

for combo in all_combinations:
    scenario = dict(zip(keys, combo))
    
    # Check Exclusions
    is_excluded = False
    for rule in exclusions:
        if all(scenario.get(k) == v for k, v in rule.items()):
            is_excluded = True
            break
    if is_excluded:
        continue

    # Enrichment
    size_label = scenario['size']
    scenario['rows'] = defs['rows'][size_label]
    scenario['ratio'] = defs['constants']['orders_per_customer']
    
    # Generate Key
    orph_val = scenario['orphan_rate']
    orph_label = defs['orphan_labels'].get(orph_val, f"orph{orph_val}")
    
    # Remove engine from key (Shared Data Architecture)
    parts = [
        size_label,
        orph_label
    ]
    
    partition_key = "_".join(parts)
    
    partition_keys.append(partition_key)
    SCENARIO_CONFIG[partition_key] = scenario

partitions_def = StaticPartitionsDefinition(partition_keys)
