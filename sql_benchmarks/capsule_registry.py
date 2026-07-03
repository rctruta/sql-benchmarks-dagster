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
"""
import os
from typing import Literal

import yaml

RegistryStatus = Literal["fresh", "duplicate", "collision"]


def _strip_meta(config: dict) -> dict:
    """Copy of config with 'meta' removed. Mirrors hasher.py:51's clean_config."""
    return {k: v for k, v in config.items() if k != "meta"}


def check_registry(
    exp_id: str,
    submitted_config: dict,
    config_archive_dir: str,
) -> RegistryStatus:
    """Classify a would-be submission against what's already sealed.

    Returns:
      "fresh"     — no archived config with this exp_id. Proceed.
      "duplicate" — archived config parses to the same dict (minus meta) as
                    the submitted one. Re-submission of a known experiment.
      "collision" — archived config parses to a DIFFERENT dict. A genuine
                    32-bit hash collision. Refuse and surface loudly.
    """
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

    if _strip_meta(archived_config) == _strip_meta(submitted_config):
        return "duplicate"
    return "collision"
