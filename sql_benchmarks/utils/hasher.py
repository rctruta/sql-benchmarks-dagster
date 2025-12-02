import hashlib
import json
import os
import sqlparse
from .common import get_target_sql_dir

def normalize_sql(content):
    return sqlparse.format(
        content,
        strip_comments=True,
        reindent=True,
        keyword_case='upper'
    )

def generate_experiment_hash(config_dict, root_dir):
    hasher = hashlib.sha256()

    # 1. Hash Config
    clean_config = {k: v for k, v in config_dict.items() if k != 'meta'}
    config_str = json.dumps(clean_config, sort_keys=True)
    hasher.update(config_str.encode('utf-8'))

    # Helper to hash directory
    def hash_folder(folder_path, extension, semantic_cleaning=False):
        if not os.path.exists(folder_path):
            return

        for root, dirs, files in os.walk(folder_path):
            for file in sorted(files):
                if file.endswith(extension):
                    full_path = os.path.join(root, file)
                    # Hash relative path for consistency
                    rel_path = os.path.relpath(full_path, root_dir)
                    hasher.update(rel_path.encode('utf-8'))
                    
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    if semantic_cleaning:
                        content = normalize_sql(content)
                    
                    hasher.update(content.encode('utf-8'))

    # 2. Hash SQL Files (Using Shared Logic)
    # The hasher asks common.py: "Where are the SQL files for this config?"
    target_sql_dir = get_target_sql_dir(config_dict)
    
    # Note: get_target_sql_dir returns absolute path from constants.
    # We hash it.
    hash_folder(target_sql_dir, ".sql", semantic_cleaning=True)

    # 3. Hash Python Assets
    assets_dir = os.path.join(root_dir, "sql_benchmarks", "assets")
    hash_folder(assets_dir, ".py", semantic_cleaning=False)

    return hasher.hexdigest()[:8]