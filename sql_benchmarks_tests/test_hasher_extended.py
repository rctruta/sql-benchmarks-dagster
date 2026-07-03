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
    sort_keys=True in json.dumps sorts recursively. Extends the top-level
    dict-ordering test to nested dicts: {execution: {a: 1, b: 2}} must hash
    the same as {execution: {b: 2, a: 1}}.
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


def test_hasher_treats_list_order_as_significant():
    """
    Documents current behavior: JSON serialization preserves list order, and
    sort_keys=True does NOT sort list elements — only dict keys. So two
    configs with reordered matrix values (or engine lists) produce different
    hashes today.

    This is the anchor test for the pending design decision: is
    matrix.<dim> a SET (order irrelevant) or a SEQUENCE (order defines
    iteration)? Today the hasher treats it as a sequence. If TODO #5b or a
    successor commits to sorting set-like lists before hashing, THIS test
    changes to `assert h1 == h2` — that flip is the migration marker.
    """
    config_1 = {
        "execution": {
            "engines": ["duckdb", "postgres"],
            "matrix": {"rows": ["medium", "large"]},
        },
    }
    config_2 = {
        "execution": {
            "engines": ["duckdb", "postgres"],
            "matrix": {"rows": ["large", "medium"]},
        },
    }
    h1 = generate_experiment_hash(config_1, "/tmp")
    h2 = generate_experiment_hash(config_2, "/tmp")
    assert h1 != h2, (
        "current hasher treats list order as significant. "
        "If this assertion flips, matrix values were made order-invariant — "
        "expected under the TODO #5b matrix-canonicalization design."
    )

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