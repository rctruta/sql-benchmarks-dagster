import yaml
import itertools
import os
from dagster import StaticPartitionsDefinition

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "experiments.yaml")

with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)

# Unpack
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
    
    # 1. Check Exclusions
    # (Helper to match exclusion rules safely)
    is_excluded = False
    for rule in exclusions:
        if all(scenario.get(k) == v for k, v in rule.items()):
            is_excluded = True
            break
    if is_excluded:
        continue

    # 2. ENRICHMENT
    # Look up Row Counts
    size_label = scenario['size']
    scenario['rows'] = defs['rows'][size_label]
    
    # Inject Constants
    scenario['ratio'] = defs['constants']['orders_per_customer']
    
    # 3. GENERATE PARTITION KEY (Using Labels)
    # Get the raw orphan rate (e.g. 0.10)
    orph_val = scenario['orphan_rate']
    
    # Look up the label: 0.10 -> "skew10"
    # Fallback: if not in YAML, format as "orph0.10"
    orph_label = defs['orphan_labels'].get(orph_val, f"orph{orph_val}")
    
    # Build the string: small_skew10_duckdb
    parts = [
        size_label,
        orph_label,
    ]
    
    partition_key = "_".join(parts)
    
    partition_keys.append(partition_key)
    SCENARIO_CONFIG[partition_key] = scenario

partitions_def = StaticPartitionsDefinition(partition_keys)