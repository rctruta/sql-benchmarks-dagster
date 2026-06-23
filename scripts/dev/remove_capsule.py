#!/usr/bin/env python3
"""
Remove a capsule and propagate the removal to the catalog — the inverse of the
publish (`git add -f`) flow.

For each Experiment ID: delete the capsule directory and its config-registry
entry, then regenerate the experiment catalog so the record disappears from
docs/experiments.md too. A *tracked* (published) capsule is removed via `git rm`
(staged — commit to finalize, so it's reversible until you do); an *untracked*
local/exploratory one is deleted outright.

Safety: only an 8-hex Experiment ID is accepted (so the target can never contain
a path separator or `..` — no traversal), and only inside RESULTS_DIR.

Usage:
    python scripts/dev/remove_capsule.py <ID> [<ID> ...]
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
from sql_benchmarks.constants import RESULTS_DIR, CONFIG_ARCHIVE_DIR  # noqa: E402

ID_RE = re.compile(r"^[0-9a-f]{8}$")


def _is_tracked(path: str) -> bool:
    r = subprocess.run(["git", "ls-files", "--error-unmatch", path],
                       cwd=REPO_ROOT, capture_output=True)
    return r.returncode == 0


def remove(exp_id: str) -> bool:
    if not ID_RE.match(exp_id):
        print(f"refusing '{exp_id}': not an 8-hex Experiment ID")
        return False
    capsule = os.path.join(RESULTS_DIR, exp_id)            # 8-hex => no traversal
    if not os.path.isdir(capsule):
        print(f"capsule {exp_id}: not found at {capsule}")
        return False

    if _is_tracked(capsule):
        subprocess.run(["git", "rm", "-r", "-q", capsule], cwd=REPO_ROOT, check=True)
        print(f"git rm {exp_id}  (staged — commit to finalize; reversible until then)")
    else:
        shutil.rmtree(capsule)
        print(f"deleted local/untracked {exp_id}")

    registry = os.path.join(CONFIG_ARCHIVE_DIR, f"config_{exp_id}.yaml")
    if os.path.exists(registry):
        os.remove(registry)
        print(f"  + removed config-registry entry config_{exp_id}.yaml")
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Remove capsule(s) and update the catalog.")
    ap.add_argument("exp_ids", nargs="+", help="8-hex Experiment IDs")
    args = ap.parse_args()

    results = [remove(i) for i in args.exp_ids]
    if any(results):
        # Propagate to the catalog so the removed record disappears from docs too.
        subprocess.run([sys.executable, os.path.join(REPO_ROOT, "scripts", "tools",
                                                     "gen_experiment_catalog.py")],
                       cwd=REPO_ROOT, check=False)
        print("catalog regenerated.")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
