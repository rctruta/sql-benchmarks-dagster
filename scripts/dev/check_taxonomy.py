"""Taxonomy-drift guard — the same shape as check_deps.py, for the category map.

WHY THIS EXISTS
---------------
`sql_benchmarks/experiments/taxonomy.yaml` is hand-authored and never written
by any code. Meanwhile `CatalogReader` discovers suites by listing SQL_DIR at
request time. So the catalog is DYNAMIC and the taxonomy is STATIC, and nothing
connected the two: add a suite directory and the taxonomy silently falls behind.

The failure is quiet, which is what makes it worth a gate. A suite missing from
the taxonomy still shows up in `list_suites` (that reads disk), so nothing looks
broken — but `suites_in_category()` and `category_counts()` never mention it.
The suite becomes invisible to exactly the category-first discovery path the
taxonomy was added to provide.

WHAT IS AND IS NOT DERIVABLE
----------------------------
This deliberately does NOT auto-generate the taxonomy, because most of it is
judgement that cannot be recovered from the filesystem:

    derivable       the SET of suite names (directories under SQL_DIR)
    NOT derivable   which categories a suite belongs to
    NOT derivable   what a category means (its description)
    NOT derivable   per-capsule overrides

Auto-generating would mean inventing category assignments, and a wrong
assignment is worse than a missing one: it is confidently wrong and nobody
reviews it. So the tool reports drift and emits a paste-ready stub; a human
still decides the categories.

USAGE
    python scripts/dev/check_taxonomy.py           # report; exit 1 on drift
    python scripts/dev/check_taxonomy.py --stub    # emit YAML to paste
"""
from __future__ import annotations

import os
import sys

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from sql_benchmarks.constants import EXPERIMENTS_DIR, SQL_DIR  # noqa: E402

TAXONOMY_PATH = os.path.join(EXPERIMENTS_DIR, "taxonomy.yaml")


def suites_on_disk() -> set:
    """Suite names as the catalog sees them: directories under SQL_DIR.

    Mirrors CatalogReader._suite_names so the two cannot disagree about what
    counts as a suite.
    """
    if not os.path.isdir(SQL_DIR):
        return set()
    return {d for d in os.listdir(SQL_DIR)
            if os.path.isdir(os.path.join(SQL_DIR, d))}


def load_taxonomy() -> dict:
    if not os.path.isfile(TAXONOMY_PATH):
        return {"categories": {}, "suites": {}, "capsules": {}}
    with open(TAXONOMY_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {
        "categories": data.get("categories") or {},
        "suites": data.get("suites") or {},
        "capsules": data.get("capsules") or {},
    }


def find_drift() -> dict:
    """Every way the taxonomy and the filesystem can disagree.

    Returns a dict of finding -> offenders. Empty dict means in sync.
    """
    tax = load_taxonomy()
    disk = suites_on_disk()
    declared = set(tax["suites"])
    vocabulary = set(tax["categories"])

    used = {c for cats in tax["suites"].values() for c in (cats or [])}
    capsule_used = {c for cats in tax["capsules"].values() for c in (cats or [])}

    drift = {
        # A new suite was added and nobody categorised it. It is discoverable
        # by name but invisible to category queries.
        "uncategorised_suites": sorted(disk - declared),
        # A suite was renamed or deleted; the taxonomy still references it, so
        # category counts include something that no longer exists.
        "stale_suite_entries": sorted(declared - disk),
        # A category used by a suite but never defined — it has no description,
        # so `list_categories` will not surface it to an agent.
        "undeclared_categories": sorted(used - vocabulary),
        # Same, via a capsule override.
        "undeclared_capsule_categories": sorted(capsule_used - vocabulary),
        # Declared with a description but attached to nothing. Not an error —
        # reported so the vocabulary can be pruned deliberately.
        "unused_categories": sorted(vocabulary - used - capsule_used),
    }
    return {k: v for k, v in drift.items() if v}


# Findings that mean the taxonomy is WRONG, versus merely untidy. Only these
# fail the gate: an unused category is a judgement call, not a defect.
BLOCKING = (
    "uncategorised_suites",
    "stale_suite_entries",
    "undeclared_categories",
    "undeclared_capsule_categories",
)


def stub_for(suites: list) -> str:
    """Paste-ready YAML for suites needing categories.

    Emitted rather than written: the categories are left empty on purpose so
    the author has to choose them. A guessed default would be reviewed by
    nobody.
    """
    if not suites:
        return ""
    lines = ["# Add under `suites:` in taxonomy.yaml and fill in the categories.",
             "# Run `python scripts/dev/check_taxonomy.py` to list valid names."]
    width = max(len(s) for s in suites) + 2
    for s in suites:
        lines.append(f"  {s + ':':<{width}} []   # TODO categorise")
    return "\n".join(lines)


def main() -> int:
    drift = find_drift()
    tax = load_taxonomy()

    print(f"suites on disk     : {len(suites_on_disk())}")
    print(f"suites in taxonomy : {len(tax['suites'])}")
    print(f"categories declared: {len(tax['categories'])}")

    if "--stub" in sys.argv:
        stub = stub_for(drift.get("uncategorised_suites", []))
        print("\n" + (stub or "# nothing to add — taxonomy covers every suite"))
        return 0

    if not drift:
        print("\nno drift.")
        return 0

    print()
    for key, items in drift.items():
        mark = "FAIL" if key in BLOCKING else "note"
        print(f"[{mark}] {key}: {', '.join(items)}")

    if drift.get("uncategorised_suites"):
        print("\nvalid category names:")
        print("  " + ", ".join(sorted(tax["categories"])))
        print("\nstub (also: --stub):")
        print(stub_for(drift["uncategorised_suites"]))

    return 1 if any(k in BLOCKING for k in drift) else 0


if __name__ == "__main__":
    sys.exit(main())
