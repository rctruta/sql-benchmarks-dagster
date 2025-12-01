import itertools
from dagster import StaticPartitionsDefinition
# 1. USE SHARED LOADER (No more manual file reading)
from .utils.common import load_active_config

# Load Context
try:
    CTX = load_active_config()
    CONFIG = CTX['full_config']
    
    # 2. EXTRACT SECTIONS
    # We default to empty dicts so we don't crash during initial setup
    DIMS = CONFIG.get("dimensions", {})
    DEFS = CONFIG.get("definitions", {})
    EXCLUSIONS = CONFIG.get("exclude", [])
    
    # Export Meta for Factories
    EXPERIMENT_META = CTX['meta']

except Exception as e:
    # Safe fallback for import time
    print(f"⚠️ Partitions Init Error: {e}")
    DIMS = {}
    DEFS = {}
    EXCLUSIONS = []
    EXPERIMENT_META = {}

# 3. GENERATE SCENARIOS (Generic Grid Search)
keys = list(DIMS.keys())
values = list(DIMS.values())
all_combinations = list(itertools.product(*values))

SCENARIO_CONFIG = {}
partition_keys = []

for combo in all_combinations:
    # Create base scenario dict
    scenario = dict(zip(keys, combo))
    
    # 4. FILTER EXCLUSIONS
    is_excluded = False
    for rule in EXCLUSIONS:
        # If every key in the rule matches the scenario, exclude it
        if all(scenario.get(k) == v for k, v in rule.items()):
            is_excluded = True
            break
    if is_excluded:
        continue

    # 5. ENRICHMENT & KEY GENERATION (The Generic Loop)
    key_parts = []
    
    for dim_name in keys:
        val = scenario[dim_name]
        
        # A. Inject Definitions (e.g., look up 'small' -> 100,000 rows)
        # We look for a block in definitions named exactly like the dimension (e.g. 'rows' for 'size'?)
        # Or more robustly: check if the dimension NAME exists in definitions
        # Current YAML structure: dimensions: [size], definitions: [rows]. 
        # We need a mapping logic or we accept direct lookup.
        
        # Let's handle the specific 'size' -> 'rows' mapping if it exists, or generic lookup
        # Better: We put everything from 'definitions' available to the asset params
        for def_key, def_val in DEFS.items():
            if isinstance(def_val, dict) and val in def_val:
                # If "small" is a key in definitions.rows, inject "rows": 100000
                # We normalize the key name (e.g. 'rows')
                scenario[def_key] = def_val[val]
            elif def_key == "constants":
                # Always inject constants
                scenario.update(def_val)

        # B. Generate Label for Partition String
        # Strategy: Look for '{dim_name}_labels' in definitions
        label_map_name = f"{dim_name}_labels" # e.g. orphan_rate_labels
        
        label = str(val) # Default to raw value
        
        # Try to find a pretty label
        # Check specific map (orphan_rate_labels)
        if label_map_name in DEFS:
             # Handle float keys carefully
             label = DEFS[label_map_name].get(val, label)
        
        # Clean up floats if no label found (0.10 -> 0.1)
        if isinstance(val, float) and label == str(val):
             label = f"{val:.2f}".rstrip('0').rstrip('.')
             # Optional: Add dim prefix if raw? e.g. "orphan0.1"
             # For now, keep it simple.
        
        key_parts.append(str(label))

    # Join: small_skew10
    partition_key = "_".join(key_parts)
    
    partition_keys.append(partition_key)
    SCENARIO_CONFIG[partition_key] = scenario

partitions_def = StaticPartitionsDefinition(partition_keys)