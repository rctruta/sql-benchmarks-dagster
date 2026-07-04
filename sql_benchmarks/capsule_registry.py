"""Capsule registry probing.

The registry at `CONFIG_ARCHIVE_DIR/config_<exp_id>.yaml` — one file per
successfully sealed capsule — is the source of truth for "has this experiment
already been run?" This module answers that question with three-way precision
so a 32-bit hash collision can never silently return the wrong capsule.

The "same 8-char exp_id" check that used to gate on `os.path.exists` alone
was correct in the common case (same config → same hash → same capsule) but
wrong in the corner case (two different configs → same 8-char hash prefix,
probability ~1 at 65k capsules): the second submission would be told "duplicate,
here are the first submission's results." A silent misdirection.

Fix: after the existence check passes, compare the archived config to the
submitted config by parsed-tree equality (Python's built-in `==` on dicts /
lists / scalars). If they agree → real duplicate. If they disagree → real
collision → refuse.

The hasher at `utils/hasher.py:51` excludes the `meta` block from the hash
input, so the comparison must too — otherwise a resubmit with a different
`meta.name` or `meta.description` would falsely trip as a collision.

Also: the hasher canonicalizes set-like paths (see
`sql_benchmarks/canonicalization.py`, TODO #5c) before hashing, so a
resubmit with matrix values reordered hashes to the same exp_id. For the
equivalence relation implemented here to agree with the hasher's, this
comparison must canonicalize both sides too — otherwise a permutation
resubmit would falsely trip as a collision.

Race close (Gap 1 / TODO #2 window): a running marker
(`results/<id>/running.json`, per running_marker.py) is treated as a
`duplicate` too — this experiment is already in flight, and letting a
second submission of the same YAML through would spawn two concurrent
runs racing over the scratchpad and results dir. The running marker
identifies the exp_id as claimed, without requiring the config archive
to exist yet.
"""
import os
from typing import Literal

import yaml

from .canonicalization import canonicalize
from .running_marker import has_running_marker

RegistryStatus = Literal["fresh", "duplicate", "collision"]


def _strip_meta(config: dict) -> dict:
    """Copy of config with 'meta' removed. Mirrors hasher.py:51's clean_config."""
    return {k: v for k, v in config.items() if k != "meta"}


def check_registry(
    exp_id: str,
    submitted_config: dict,
    config_archive_dir: str,
    results_dir: str = None,
) -> RegistryStatus:
    """Classify a would-be submission against what's already sealed OR
    currently running.

    Returns:
      "fresh"     — no archived config AND no running marker with this exp_id.
                    Proceed.
      "duplicate" — same experiment already known: either currently running
                    (running marker present) or archived (config in registry
                    with a parsed-tree equal to the submitted one, minus
                    meta, canonicalized).
      "collision" — archived config parses to a DIFFERENT dict. A genuine
                    32-bit hash collision. Refuse and surface loudly.

    `results_dir` is optional so existing callers that only care about the
    archive check don't need to pass it — but callers that want the race
    close for in-flight runs (API submission handler, coordinator) should
    pass their RESULTS_DIR so the running-marker check fires.
    """
    # Race close: if the experiment is currently running (running marker
    # present), it's the same experiment already in flight. Refuse the
    # resubmission before it spawns a second concurrent run.
    if results_dir and has_running_marker(results_dir, exp_id):
        return "duplicate"

    archived_path = os.path.join(config_archive_dir, f"config_{exp_id}.yaml")
    if not os.path.exists(archived_path):
        return "fresh"

    try:
        with open(archived_path) as f:
            archived_config = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        # Cannot read or parse an existing archived config — refuse to
        # overwrite what we can't verify. Treated as a collision so the
        # caller escalates rather than silently overwriting.
        return "collision"

    # Canonicalize both sides so the equivalence relation matches the
    # hasher's: matrix-value permutations and engine-list permutations
    # compare equal (they hash equal too — see canonicalization.py).
    a = _strip_meta(canonicalize(archived_config))
    b = _strip_meta(canonicalize(submitted_config))
    if a == b:
        return "duplicate"
    return "collision"
