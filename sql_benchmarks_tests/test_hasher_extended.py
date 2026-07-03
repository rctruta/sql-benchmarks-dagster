import pytest
from sql_benchmarks.utils.hasher import normalize_sql, generate_experiment_hash
import ast
# ==========================================
# 1. SQL SEMANTIC EQUIVALENCE
# ==========================================
def test_hasher_ignores_case_on_keywords():
    """Agents might mix case (SELECT vs select). Hasher should ignore it."""
    sql_1 = "SELECT * FROM users WHERE id = 1"
    sql_2 = "select * from users where id = 1"
    
    # Note: normalize_sql uses sqlparse(keyword_case='upper')
    # It guarantees keywords match. 
    # Identifiers (table names) might still differ depending on sqlparse version,
    # but at a minimum, the structure should normalize.
    assert normalize_sql(sql_1) == normalize_sql(sql_2)

def test_hasher_ignores_complex_comments():
    """Agents often add 'Chain of Thought' reasoning in comments."""
    clean_sql = "SELECT count(*) FROM orders"
    
    agent_sql = """
        /* Reasoning: I need to count the orders to verify
           the impact of the join explosion.
        */
        SELECT count(*) -- The target metric
        FROM orders -- The source table
        ;
    """
    
    assert normalize_sql(clean_sql) == normalize_sql(agent_sql)

def test_hasher_ignores_tabs_and_newlines():
    """Agents have inconsistent indentation styles."""
    sql_1 = "SELECT a, b FROM table"
    sql_2 = "SELECT\n\ta,\n\tb\nFROM\n\ttable"
    
    assert normalize_sql(sql_1) == normalize_sql(sql_2)

def test_hasher_preserves_jinja_templates():
    """
    CRITICAL: Normalization must NOT mangle Jinja tags.
    """
    raw_template = "SELECT * FROM {{ table_name }} WHERE id = {{ id_val }}"
    
    # Our new normalizer converts to LOWERCASE. 
    # So we expect the output to be lowercased.
    normalized = normalize_sql(raw_template)
    
    # Assertions should check for the lowercased version
    assert "{{ table_name }}" in normalized
    assert "{{ id_val }}" in normalized
    
    # Verify structure wasn't lost
    assert "select * from" in normalized
# ==========================================
# 2. CONFIG DICTIONARY STABILITY
# ==========================================
def test_hasher_handles_dict_key_ordering():
    """
    YAML dictionaries are unordered. 
    {a: 1, b: 2} must hash same as {b: 2, a: 1}.
    """
    config_1 = {
        "dataset": {"tables": ["orders"]},
        "execution": {"replication": 5}
    }
    
    config_2 = {
        "execution": {"replication": 5},
        "dataset": {"tables": ["orders"]}
    }
    
    # We pass a dummy root_dir because we only care about config hashing here
    h1 = generate_experiment_hash(config_1, "/tmp")
    h2 = generate_experiment_hash(config_2, "/tmp")
    
    assert h1 == h2

def test_hasher_ignores_meta_block():
    """
    Changing the description or experiment_id shouldn't trigger a re-run.
    The 'meta' block is for humans, not for execution logic.
    """
    config_1 = {
        "meta": {"description": "Run 1", "experiment_id": "abc"},
        "dataset": {"tables": ["t1"]}
    }

    config_2 = {
        "meta": {"description": "Run 2 - fixed typo", "experiment_id": "xyz"},
        "dataset": {"tables": ["t1"]}
    }

    h1 = generate_experiment_hash(config_1, "/tmp")
    h2 = generate_experiment_hash(config_2, "/tmp")

    assert h1 == h2


def test_hasher_handles_nested_dict_key_ordering():
    """
    sort_keys=True in json.dumps recurses into nested dicts. Extends the
    top-level test to prove nested reordering is also a no-op for the hash.
    """
    config_1 = {
        "execution": {
            "engines": ["duckdb"],
            "replication": 5,
            "matrix": {"rows": [1000, 10000]},
        },
        "dataset": {"tables": {"t1": {"rows": 1000, "columns": []}}},
    }
    config_2 = {
        "dataset": {"tables": {"t1": {"columns": [], "rows": 1000}}},
        "execution": {
            "matrix": {"rows": [1000, 10000]},
            "replication": 5,
            "engines": ["duckdb"],
        },
    }
    h1 = generate_experiment_hash(config_1, "/tmp")
    h2 = generate_experiment_hash(config_2, "/tmp")
    assert h1 == h2, "nested dict key reordering must not change the hash"


def test_hasher_canonicalizes_set_like_matrix_values():
    """
    execution.matrix.<dim> is declared set-like in SET_LIKE_PATHS. Two
    configs that differ only in the ORDER of matrix values must hash the
    same — the cartesian product is identical, so the experiment is
    identical.
    """
    config_1 = {"execution": {"engines": ["duckdb"], "matrix": {"rows": ["medium", "large"]}}}
    config_2 = {"execution": {"engines": ["duckdb"], "matrix": {"rows": ["large", "medium"]}}}
    h1 = generate_experiment_hash(config_1, "/tmp")
    h2 = generate_experiment_hash(config_2, "/tmp")
    assert h1 == h2


def test_hasher_canonicalizes_set_like_engines():
    """
    execution.engines is declared set-like. [duckdb, postgres] and
    [postgres, duckdb] run the same experiment.
    """
    config_1 = {"execution": {"engines": ["duckdb", "postgres"], "matrix": {"rows": [1000]}}}
    config_2 = {"execution": {"engines": ["postgres", "duckdb"], "matrix": {"rows": [1000]}}}
    h1 = generate_experiment_hash(config_1, "/tmp")
    h2 = generate_experiment_hash(config_2, "/tmp")
    assert h1 == h2


def test_hasher_keeps_non_set_like_list_order_significant():
    """
    Lists NOT declared in SET_LIKE_PATHS still care about order. Column
    lists are the load-bearing example: DDL column order is part of the
    schema and can affect index prefix semantics. Two configs with
    reordered column definitions must NOT hash the same.
    """
    config_1 = {
        "dataset": {
            "tables": {
                "t1": {
                    "columns": [
                        {"name": "id", "provider": "sequence"},
                        {"name": "val", "provider": "random_int"},
                    ]
                }
            }
        }
    }
    config_2 = {
        "dataset": {
            "tables": {
                "t1": {
                    "columns": [
                        {"name": "val", "provider": "random_int"},
                        {"name": "id", "provider": "sequence"},
                    ]
                }
            }
        }
    }
    h1 = generate_experiment_hash(config_1, "/tmp")
    h2 = generate_experiment_hash(config_2, "/tmp")
    assert h1 != h2, "sequence-like lists (columns) must still be order-sensitive"

from sql_benchmarks.utils.hasher import normalize_python

# ... previous SQL tests ...

# ==========================================
# 3. PYTHON LOGIC STABILITY
# ==========================================
def test_python_normalization_ignores_comments():
    """Verify that adding comments doesn't change the logic hash."""
    code_1 = """
def calculate(a, b):
    return a + b
    """
    
    code_2 = """
def calculate(a, b):
    # This is a complex calculation
    # We add a and b together
    return a + b  # Result
    """
    
    assert normalize_python(code_1) == normalize_python(code_2)

def test_python_normalization_ignores_docstrings():
    """Verify that documentation changes don't trigger re-runs."""
    code_1 = """
class Benchmark:
    def run(self):
        pass
    """
    
    code_2 = """
class Benchmark:
    '''
    The Benchmark Class.
    Updated: 2024-01-01
    '''
    def run(self):
        '''Executes the query'''
        pass
    """
    
    assert normalize_python(code_1) == normalize_python(code_2)

def test_python_normalization_standardizes_formatting():
    """Verify that messy whitespace doesn't matter."""
    code_1 = "x = [1, 2, 3]"
    code_2 = "x = [ 1,   2, 3 ]"
    
    assert normalize_python(code_1) == normalize_python(code_2)    