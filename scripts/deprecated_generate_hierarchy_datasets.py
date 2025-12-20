import os
import yaml
from sql_benchmarks.constants import DATA_DIR
from sql_benchmarks.plugins.data_sources import declarative_gen

# Static Config for the 3 Topologies
TARGET_DIR = os.path.join(DATA_DIR, "staging")

DEFINITIONS = {
    "uniform": {"distribution": "uniform"},
    "chain":   {"distribution": "chain"},
    "zipf":    {"distribution": "zipf", "zipf_a": 2.0}
}

ROW_COUNT = 10

def get_config(topo, params):
    """Returns a declarative config for the specific topology."""
    return {
        "tables": {
            f"hierarchy_{topo}": {
                "rows": ROW_COUNT,
                "columns": [
                    {"name": "id", "provider": "sequence", "primary_key": True},
                    {
                        "name": "parent_id", 
                        "provider": "foreign_key", 
                        "target_table": f"hierarchy_{topo}",
                        "target_column": "id",
                        "distribution": params.get("distribution"),
                        "zipf_a": params.get("zipf_a"),
                    },
                    {
                        "name": "name", 
                        "provider": "text_concat", 
                        "source": "id", 
                        "prefix": f"node_{topo}_"
                    }
                ]
            }
        }
    }

def main():
    print(f"Generating Hierarchy Datasets ({ROW_COUNT} rows)...")
    os.makedirs(TARGET_DIR, exist_ok=True)
    
    for topo, params in DEFINITIONS.items():
        print(f"  -> Generating {topo}...")
        
        # 1. Build Config
        dataset_cfg = get_config(topo, params)
        table_name = f"hierarchy_{topo}"
        
        # 2. Define Output Path
        target_path = os.path.join(TARGET_DIR, f"{table_name}.parquet")
        
        # 3. Generate
        # declarative_gen.generate expects (context, params, table, path, config)
        # context is used for logging/partitions, can be None for strict script usage?
        # Let's check declarative_gen usage of context. It's unused in the core logic IIRC.
        declarative_gen.generate(None, {"rows": ROW_COUNT}, table_name, target_path, dataset_cfg)
        
        print(f"     [OK] Saved to {target_path}")

if __name__ == "__main__":
    main()
