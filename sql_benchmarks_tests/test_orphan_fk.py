"""orphan_rate on the foreign_key provider: a fraction of keys point to no parent."""
import numpy as np
from sql_benchmarks.utils.providers import generate_foreign_key


def test_default_is_orphan_free():
    np.random.seed(1)
    fk = generate_foreign_key(5000, "child", target_rows=5000)
    assert (fk >= 1).all() and (fk <= 5000).all()   # every key references a real parent


def test_orphan_rate_injects_unmatched_keys():
    np.random.seed(1)
    fk = generate_foreign_key(20000, "child", target_rows=10000, orphan_rate=0.1)
    orphans = fk > 10000                              # beyond the parent id range => no match
    frac = orphans.mean()
    assert 0.08 < frac < 0.12                         # ~10%, allowing sampling noise
    assert (fk[~orphans] >= 1).all()                  # the rest are still valid


def test_orphan_rate_zero_is_noop():
    np.random.seed(2)
    a = generate_foreign_key(3000, "child", target_rows=3000, orphan_rate=0.0)
    assert (a <= 3000).all()
