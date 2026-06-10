"""
Tests for the generate_zipf_edges provider.

Validates graph topology guarantees, output shape, column contents,
and Zipf degree-distribution properties without touching disk or TypeDB.
"""
import pytest
import numpy as np
from sql_benchmarks.utils.providers import generate_zipf_edges


# ---------------------------------------------------------------------------
# 1. Output structure
# ---------------------------------------------------------------------------

def test_returns_dict_with_two_keys():
    result = generate_zipf_edges(100, n_nodes=50)
    assert isinstance(result, dict)
    assert "from_id" in result
    assert "to_id" in result


def test_arrays_have_correct_length():
    result = generate_zipf_edges(200, n_nodes=100)
    assert len(result["from_id"]) == 200
    assert len(result["to_id"])   == 200


def test_arrays_are_integer_dtype():
    result = generate_zipf_edges(50, n_nodes=30)
    assert result["from_id"].dtype in (np.int64, np.int32)
    assert result["to_id"].dtype   in (np.int64, np.int32)


# ---------------------------------------------------------------------------
# 2. Node ID validity
# ---------------------------------------------------------------------------

def test_all_from_ids_within_node_range():
    n_nodes = 50
    result  = generate_zipf_edges(200, n_nodes=n_nodes)
    assert result["from_id"].min() >= 1
    assert result["from_id"].max() <= n_nodes


def test_all_to_ids_within_node_range():
    n_nodes = 50
    result  = generate_zipf_edges(200, n_nodes=n_nodes)
    assert result["to_id"].min() >= 1
    assert result["to_id"].max() <= n_nodes


def test_no_self_loops():
    """No edge should connect a node to itself."""
    result = generate_zipf_edges(500, n_nodes=100)
    assert not any(f == t for f, t in zip(result["from_id"], result["to_id"]))


# ---------------------------------------------------------------------------
# 3. Exact row count
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rows", [1, 10, 100, 500, 2000])
def test_exact_row_count(rows):
    result = generate_zipf_edges(rows, n_nodes=200)
    assert len(result["from_id"]) == rows
    assert len(result["to_id"])   == rows


# ---------------------------------------------------------------------------
# 4. Reproducibility
# ---------------------------------------------------------------------------

def test_same_seed_produces_same_edges():
    r1 = generate_zipf_edges(200, n_nodes=100, seed=7)
    r2 = generate_zipf_edges(200, n_nodes=100, seed=7)
    np.testing.assert_array_equal(r1["from_id"], r2["from_id"])
    np.testing.assert_array_equal(r1["to_id"],   r2["to_id"])


def test_different_seeds_produce_different_edges():
    r1 = generate_zipf_edges(200, n_nodes=100, seed=1)
    r2 = generate_zipf_edges(200, n_nodes=100, seed=2)
    assert not np.array_equal(r1["from_id"], r2["from_id"])


# ---------------------------------------------------------------------------
# 5. Zipf degree-distribution properties
# ---------------------------------------------------------------------------

def test_out_degree_is_skewed():
    """A few nodes should have much higher out-degree than the median."""
    result = generate_zipf_edges(2000, n_nodes=500, zipf_a=2.0)
    from collections import Counter
    counts  = Counter(result["from_id"].tolist())
    degrees = sorted(counts.values(), reverse=True)
    # Top node should have at least 5× the median degree
    median_deg = np.median(degrees)
    max_deg    = degrees[0]
    assert max_deg >= 5 * max(median_deg, 1)


def test_higher_zipf_a_produces_less_skew():
    """Higher a → more uniform distribution → lower max/median ratio."""
    r_skewed  = generate_zipf_edges(2000, n_nodes=500, zipf_a=1.3, seed=42)
    r_uniform = generate_zipf_edges(2000, n_nodes=500, zipf_a=3.5, seed=42)

    from collections import Counter

    def max_median_ratio(arr):
        counts  = Counter(arr.tolist())
        degrees = sorted(counts.values(), reverse=True)
        return degrees[0] / max(np.median(degrees), 1)

    ratio_skewed  = max_median_ratio(r_skewed["from_id"])
    ratio_uniform = max_median_ratio(r_uniform["from_id"])
    assert ratio_skewed > ratio_uniform


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------

def test_small_graph_does_not_crash():
    """Minimum viable graph: 3 nodes, 2 edges."""
    result = generate_zipf_edges(2, n_nodes=3)
    assert len(result["from_id"]) == 2


def test_more_edges_than_nodes():
    """Edge count >> node count is normal for dense graphs."""
    result = generate_zipf_edges(1000, n_nodes=50)
    assert len(result["from_id"]) == 1000
