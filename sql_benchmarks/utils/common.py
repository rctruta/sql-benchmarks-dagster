import os
import yaml
import jinja2
import jinja2.meta
from sql_benchmarks.constants import ACTIVE_CONFIG_PATH

def load_active_config():
    """
    Centralized config loader.
    Returns a dict with: 'engines', 'tables', 'dataset_config', 'meta', 'full_config'
    """
    if not os.path.exists(ACTIVE_CONFIG_PATH):
        raise FileNotFoundError(f"CRITICAL: Active config not found at {ACTIVE_CONFIG_PATH}")

    with open(ACTIVE_CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)

    # 1. Validate Engines
    if "engines" not in config:
        raise ValueError(f"CRITICAL: 'engines' list missing in active.yaml")
    
    # 2. Validate Dataset
    if 'dataset' not in config:
        raise ValueError(f"CRITICAL: 'dataset' block missing in active.yaml")
        
    dataset_conf = config['dataset']
    if 'tables' not in dataset_conf:
        raise ValueError(f"CRITICAL: 'dataset.tables' missing in active.yaml")
    
    # 3. Parse Tables (Support List or Dict format)
    raw_tables = dataset_conf['tables']
    if isinstance(raw_tables, list):
        # Normalize to dict: ["a", "b"] -> {"a": {}, "b": {}}
        tables_dict = {t: {} for t in raw_tables}
    elif isinstance(raw_tables, dict):
        tables_dict = raw_tables
    else:
        raise ValueError("'dataset.tables' must be a list or dictionary.")

    # 4. Return Structured Context
    return {
        "full_config": config,
        "engines": config["engines"],
        "tables": tables_dict,          # Dictionary of table configs
        "table_names": list(tables_dict.keys()), # List of names
        "dataset_config": dataset_conf,
        "meta": config.get("meta", {"experiment_id": "default"})
    }

def get_tables_used_in_sql(sql_path, valid_tables_set):
    """
    Parses Jinja to find dependencies.
    """
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

def get_data_dependencies(table_config):
    """
    Scans a table configuration (from YAML) to find upstream dependencies.
    e.g. if column uses 'foreign_key', we depend on the target table.
    """
    deps = set()
    columns = table_config.get('columns', [])
    
    for col in columns:
        if col.get('provider') == 'foreign_key':
            target = col.get('target_table')
            if target:
                deps.add(target)
    
    return list(deps)