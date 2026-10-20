"""Reader for the category taxonomy at
`sql_benchmarks/experiments/taxonomy.yaml`.

Cheap and stateless — reloads on every call so edits to the YAML take
effect without restarting the API.

Categories are the answer to *"which slice of the suite space is
relevant to my question?"*. Before taxonomy, an agent had to receive
all suites (with their full SQL — the 88 KB payload at turn 1 of the
first live-fire run). With taxonomy, the agent starts with a small
`list_categories` call and drills into a category-filtered
`list_suites` next.
"""
import os
from typing import Dict, List

import yaml

from ...constants import EXPERIMENTS_DIR


TAXONOMY_PATH = os.path.join(EXPERIMENTS_DIR, "taxonomy.yaml")


def _load() -> dict:
    if not os.path.isfile(TAXONOMY_PATH):
        return {"categories": {}, "suites": {}, "capsules": {}}
    with open(TAXONOMY_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {
        "categories": data.get("categories") or {},
        "suites": data.get("suites") or {},
        "capsules": data.get("capsules") or {},
    }


def list_categories() -> Dict[str, str]:
    """Canonical vocabulary: `{category_name: description}`."""
    return _load()["categories"]


#: Bucket for suites present on disk but absent from taxonomy.yaml. Returning
#: this rather than [] is what keeps a newly added suite DISCOVERABLE: with an
#: empty list it appeared in list_suites (which reads the filesystem) but was
#: invisible to suites_in_category() and category_counts() for every category,
#: so category-first browsing could never reach it. The module docstring had
#: long claimed this bucket existed; until 2026-08-10 it did not.
UNCATEGORIZED = "uncategorized"


def suite_categories(suite_name: str) -> List[str]:
    """Categories for a suite, or [UNCATEGORIZED] if it has no entry.

    Never returns an empty list for a real suite: silence would drop it out of
    every category query with no signal that it had been missed. Drift is
    caught earlier by scripts/dev/check_taxonomy.py, but this makes the
    degraded state visible rather than absent.
    """
    cats = _load()["suites"].get(suite_name)
    return list(cats) if cats else [UNCATEGORIZED]


def capsule_categories(exp_id: str, suite_name: str | None) -> List[str]:
    """Capsule categories: explicit override + inherited-from-suite,
    deduped and sorted. `suite_name` may be None if the capsule's
    config didn't declare one — in that case only the explicit
    override applies."""
    tax = _load()
    explicit = set(tax["capsules"].get(exp_id) or [])
    inherited = set(tax["suites"].get(suite_name) or []) if suite_name else set()
    return sorted(explicit | inherited)


def suites_in_category(category: str) -> List[str]:
    """Suites tagged with `category`.

    Querying UNCATEGORIZED lists suites on disk that the taxonomy does not
    cover — the drift, surfaced through the same API an agent already uses
    instead of requiring a separate tool.
    """
    tax = _load()
    if category == UNCATEGORIZED:
        from ...constants import SQL_DIR
        if not os.path.isdir(SQL_DIR):
            return []
        disk = {d for d in os.listdir(SQL_DIR)
                if os.path.isdir(os.path.join(SQL_DIR, d))}
        return sorted(disk - set(tax["suites"]))
    return sorted(name for name, cats in tax["suites"].items() if category in (cats or []))


def category_counts() -> Dict[str, int]:
    """How many suites tag each category. Small helper the API uses to
    surface non-empty categories with counts."""
    tax = _load()
    counts: Dict[str, int] = {c: 0 for c in tax["categories"]}
    for cats in tax["suites"].values():
        for c in cats or []:
            counts[c] = counts.get(c, 0) + 1
    return counts
