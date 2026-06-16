#!/usr/bin/env python3
"""
Backfill queries/ into already-published capsules.

For each capsule, embeds the SQL its engines actually ran (selected dialects,
via utils.common.copy_suite_queries) and re-computes the integrity seal. This
does NOT re-run any experiment and does NOT change the Experiment ID — the ID
hashes the suite from source, not the capsule. After running this, the seal's
sidecars are stale: re-timestamp with timestamp_capsule.py and re-sign the
release tag (manual).

Usage:  python scripts/dev/backfill_queries.py <id> [<id> ...]
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from sql_benchmarks.utils.common import copy_suite_queries
from sql_benchmarks.utils.hasher import generate_integrity_seal

RESULTS = os.path.join(REPO_ROOT, "sql_benchmarks", "experiments", "results")


def backfill(exp_id: str) -> None:
    capsule = os.path.join(RESULTS, exp_id)
    if not os.path.isdir(capsule):
        print(f"{exp_id}: MISSING — skipped")
        return
    n = copy_suite_queries(capsule)
    seal_path = os.path.join(capsule, "integrity.seal")
    resealed = os.path.exists(seal_path)
    if resealed:
        with open(seal_path, "w") as f:
            f.write(generate_integrity_seal(capsule))
    print(f"{exp_id}: {n} query file(s) embedded; resealed={resealed}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for exp_id in sys.argv[1:]:
        backfill(exp_id)
