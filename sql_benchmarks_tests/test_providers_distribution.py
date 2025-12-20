import pytest
import numpy as np
from sql_benchmarks.plugins.data_sources import providers

def test_chain_distribution():
    # Chain: parent = id - 1 (with 1->1 handling)
    # ids: 1, 2, 3, 4, 5
    # exp: 1, 1, 2, 3, 4
    res = providers.generate_foreign_key(rows=5, table_name="test", distribution="chain")
    assert np.all(res == [1, 1, 2, 3, 4])

def test_zipf_distribution():
    # Zipf should produce heavily skewed data (mostly 1s)
    rows = 1000
    res = providers.generate_foreign_key(rows=rows, table_name="test", distribution="zipf", zipf_a=2.0)
    
    # Check range
    assert res.min() >= 1
    
    # Check skew: count(1) should be > count(rows/2)
    ones = np.sum(res == 1)
    
    # Basic stat check: with a=2, P(1) ~ 60%
    assert ones > (rows * 0.4), f"Expected Zipf to generate many 1s, got {ones}/{rows}"

def test_uniform_distribution():
    rows = 1000
    res = providers.generate_foreign_key(rows=rows, table_name="test", distribution="uniform")
    
    # Check randomness (not all same)
    assert len(np.unique(res)) > 100 
    assert res.min() >= 1
    assert res.max() <= 1000
