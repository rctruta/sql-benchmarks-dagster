"""Discovery over the PUBLISHED capsule corpus — the lab's own literature.

"Published" = git-tracked AND sealed (`integrity.seal` present), the same
definition `scripts/tools/verify_doc_claims.py` enforces for doc citations.
Local/transient capsules (agent runs, WIP) are excluded by construction:
they are not in git.

Why this exists (edge-case 6): the agent's tool surface exposed NONE of
the published corpus — it would re-run (and re-pay for) experiments the
repo already answers. This module is the *discovery* half only; reading
a found capsule reuses the existing projections (`get_experiment_summary`
et al. work on any capsule on disk). One new tool, everything else
already existed — progressive disclosure again.

Derived, never hand-typed: descriptions come from the archived config's
own `meta.description`, categories from `taxonomy.yaml` (capsule override
+ suite inheritance). See [[doc-verification-workflow]]: derive or check,
never retype a capsule fact.
"""
import os
import subprocess
from typing import List, Optional

import yaml

from ...constants import CONFIG_ARCHIVE_DIR, RESULTS_DIR, ROOT_DIR
from ..data.taxonomy import capsule_categories


def _git_tracked_capsule_ids() -> set:
    out = subprocess.run(
        ["git", "ls-files", "sql_benchmarks/experiments/results/"],
        cwd=ROOT_DIR, capture_output=True, text=True,
    )
    ids = set()
    for line in out.stdout.splitlines():
        parts = line.split("/")
        if len(parts) > 4:  # .../results/<ID>/<file>
            ids.add(parts[3])
    return ids


def _sealed(exp_id: str) -> bool:
    return os.path.exists(os.path.join(RESULTS_DIR, exp_id, "integrity.seal"))


def _capsule_meta(exp_id: str) -> dict:
    """suite / description / engines, derived from the capsule's own
    archived config (results copy first, archive fallback)."""
    for path in (
        os.path.join(RESULTS_DIR, exp_id, "experiment_config.yaml"),
        os.path.join(CONFIG_ARCHIVE_DIR, f"config_{exp_id}.yaml"),
    ):
        if os.path.exists(path):
            try:
                with open(path) as f:
                    cfg = yaml.safe_load(f) or {}
                execution = cfg.get("execution") or {}
                meta = cfg.get("meta") or {}
                return {
                    "suite": execution.get("test_suite"),
                    "engines": execution.get("engines") or [],
                    "description": (str(meta.get("description") or meta.get("name") or "")
                                    .strip()[:300]),
                }
            except (yaml.YAMLError, OSError):
                continue
    return {"suite": None, "engines": [], "description": ""}


def search_published_capsules(category: Optional[str] = None) -> List[dict]:
    """List published (git-tracked + sealed) capsules, optionally filtered
    by taxonomy category. Small payload: id, suite, engines, categories,
    one-line description. Read a hit with the existing projections
    (`get_experiment_summary <id>` etc.)."""
    out = []
    for exp_id in sorted(_git_tracked_capsule_ids()):
        if not _sealed(exp_id):
            continue
        meta = _capsule_meta(exp_id)
        cats = capsule_categories(exp_id, meta["suite"])
        if category and category not in cats:
            continue
        out.append({
            "experiment_id": exp_id,
            "suite": meta["suite"],
            "engines": meta["engines"],
            "categories": cats,
            "description": meta["description"],
        })
    return out
