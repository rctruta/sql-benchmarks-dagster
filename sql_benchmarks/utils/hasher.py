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

    def hash_folder(folder_path, extension, normalizer=None, exclude_dirs=()):
        if not os.path.exists(folder_path): return

        for root, dirs, files in os.walk(folder_path):
            dirs[:] = sorted(d for d in dirs if d not in exclude_dirs)
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

    # 3. Hash ALL Python that can change what a measurement means: the whole
    #    package — orchestration (assets/), engines (resources/), data
    #    generators (plugins/), and the root/utils machinery (config_loader
    #    assembles engine_params; system.py owns the cold-cache primitive).
    #    Excluded: api/ only READS results — it cannot affect a measurement —
    #    and experiments/ holds configs/results, which are hashed separately.
    #    The ID fingerprints the QUESTION; runtime conditions (engine
    #    versions, hardware) are recorded in the capsule metadata instead.
    hash_folder(
        os.path.join(root_dir, "sql_benchmarks"),
        ".py",
        normalizer=normalize_python,
        exclude_dirs=("api", "experiments", "__pycache__"),
    )

    return hasher.hexdigest()[:8]

def generate_integrity_seal(results_dir):
    """
    Generates a SHA-256 seal for the entire results capsule.
    Hashes the src snapshot + the results CSV/fragments.
    """
    hasher = hashlib.sha256()
    
    # 1. Walk results_dir and hash all files
    # This includes the 'src' snapshot and the generated CSV/JSON
    for root, dirs, files in os.walk(results_dir):
        # Sort files to ensure deterministic hashing
        for file in sorted(files):
            if file == "integrity.seal": continue # Don't hash the seal itself
            
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, results_dir)
            
            # Hash metadata
            hasher.update(rel_path.encode('utf-8'))
            
            # Hash content
            with open(file_path, 'rb') as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
                    
    return hasher.hexdigest()