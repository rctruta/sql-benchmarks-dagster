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


def suite_categories(suite_name: str) -> List[str]:
    return list(_load()["suites"].get(suite_name) or [])


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
    tax = _load()
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
