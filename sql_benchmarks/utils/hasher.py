import hashlib
import json
import os
import re
import ast
from .common import get_target_sql_dir

def normalize_sql(content):
    """
    Standardizes SQL for hashing using Regex.
    Robust to Agent formatting, comments, and Jinja templates.
    """
    # 1. Remove Block Comments /* ... */
    content = re.sub(r'/\*[\s\S]*?\*/', ' ', content)
    
    # 2. Remove Line Comments -- ...
    content = re.sub(r'--.*', ' ', content)
    
    # 3. Collapse Whitespace (Handling newlines/tabs)
    content = " ".join(content.split())
    
    # 4. Remove Trailing Semicolon (
    content = content.strip().rstrip(';').strip()
    
    # 5. Canonicalize Case (Select -> select)
    return content.lower()
def normalize_python(content):
    """
    Parses Python code to AST and regenerates it.
    Ignores comments, docstrings, and formatting.
    """
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef, ast.Module)):
                continue
            if not (node.body and isinstance(node.body[0], ast.Expr)):
                continue
            val = node.body[0].value
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                node.body.pop(0) # Remove Docstring
        return ast.unparse(tree)
    except SyntaxError:
        return content

def generate_experiment_hash(config_dict, root_dir):
    hasher = hashlib.sha256()

    # 1. Hash Config
    clean_config = {k: v for k, v in config_dict.items() if k != 'meta'}
    config_str = json.dumps(clean_config, sort_keys=True)
    hasher.update(config_str.encode('utf-8'))

    def hash_folder(folder_path, extension, normalizer=None):
        if not os.path.exists(folder_path): return

        for root, dirs, files in os.walk(folder_path):
            for file in sorted(files):
                if file.endswith(extension):
                    rel_path = os.path.relpath(os.path.join(root, file), root_dir)
                    hasher.update(rel_path.encode('utf-8'))
                    
                    with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    if normalizer:
                        content = normalizer(content)
                    
                    hasher.update(content.encode('utf-8'))

    # 2. Hash SQL Files
    target_sql_dir = get_target_sql_dir(config_dict)
    hash_folder(target_sql_dir, ".sql", normalizer=normalize_sql)

    # 3. Hash Python Assets
    assets_dir = os.path.join(root_dir, "sql_benchmarks", "assets")
    hash_folder(assets_dir, ".py", normalizer=normalize_python)

    return hasher.hexdigest()[:8]