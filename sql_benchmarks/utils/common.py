import os
import yaml
import jinja2
import jinja2.meta
from sql_benchmarks.constants import ACTIVE_CONFIG_PATH

def load_active_config():
    """
    Loads and validates the active experiment configuration.
    Returns: (full_config, engines, tables_list, meta)
    """
    if not os.path.exists(ACTIVE_CONFIG_PATH):
        raise FileNotFoundError(f"CRITICAL: Active config not found at {ACTIVE_CONFIG_PATH}")

    with open(ACTIVE_CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)

    if "engines" not in config:
        raise ValueError(f"CRITICAL: '{ACTIVE_CONFIG_PATH}' is missing 'engines' list.")
    
    if 'dataset' not in config or 'tables' not in config['dataset']:
        raise ValueError(f"CRITICAL: '{ACTIVE_CONFIG_PATH}' is missing 'dataset.tables' list.")

    return (
        config, # <--- NEW: Return the full dict
        config["engines"], 
        config['dataset']['tables'],
        config.get("meta", {"experiment_id": "default"})
    )

def get_tables_used_in_sql(sql_path, valid_tables_set):
    # (No changes here, keep existing logic)
    with open(sql_path, "r") as f:
        raw_template = f.read()

    env = jinja2.Environment()
    try:
        ast = env.parse(raw_template)
        required_vars = jinja2.meta.find_undeclared_variables(ast)
    except Exception as e:
        print(f"⚠️ Error parsing Jinja in {sql_path}: {e}")
        return [], raw_template

    used_tables = []
    for var in required_vars:
        if var.endswith("_table"):
            table_name = var.replace("_table", "")
            if table_name in valid_tables_set:
                used_tables.append(table_name)
    
    return used_tables, raw_template