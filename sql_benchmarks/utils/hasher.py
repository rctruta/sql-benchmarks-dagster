import hashlib
import json
import os
import sqlparse 

def normalize_sql(sql_content):
    """
    Strips comments and normalizes whitespace so that 
    'SELECT * FROM table' and 
    'SELECT * FROM table -- comment'
    produce the SAME hash.
    """
    # format() handles stripping comments and cleaning up whitespace
    return sqlparse.format(
        sql_content, 
        strip_comments=True, 
        reindent=True, 
        keyword_case='upper'
    )

def generate_experiment_hash(config_dict, root_dir):
    hasher = hashlib.sha256()

    # 1. Hash Config (Sorted JSON)
    config_str = json.dumps(config_dict, sort_keys=True)
    hasher.update(config_str.encode('utf-8'))

    # Helper to hash directory
    def hash_directory(folder, extension, normalize=False):
        for root, dirs, files in os.walk(folder):
            for file in sorted(files):
                if file.endswith(extension):
                    file_path = os.path.join(root, file)
                    
                    # Hash the Relative Path (Structure matters)
                    rel_path = os.path.relpath(file_path, root_dir)
                    hasher.update(rel_path.encode('utf-8'))
                    
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                        # SEMANTIC FIX: Normalize if it's SQL
                        if normalize and extension == ".sql":
                            clean_content = normalize_sql(content)
                            hasher.update(clean_content.encode('utf-8'))
                        else:
                            # For Python/other files, keep byte-level hashing
                            hasher.update(content.encode('utf-8'))

    # 2. Hash SQL Files (With Semantic Normalization)
    sql_dir = os.path.join(root_dir, "sql_benchmarks", "scripts", "sql")
    hash_directory(sql_dir, ".sql", normalize=True)

    # 3. Hash Python Assets (Strict)
    assets_dir = os.path.join(root_dir, "sql_benchmarks", "assets")
    hash_directory(assets_dir, ".py", normalize=False)

    return hasher.hexdigest()[:8]