"""Rules for canonicalizing a config dict before hashing.

Some YAML fields are SETS — the order in which the author wrote the elements
carries no semantic meaning. For example, ``execution.engines: [duckdb, postgres]``
runs the same experiment as ``[postgres, duckdb]``: both submit both engines,
same partitions, same measurements. Others are SEQUENCES where position
matters: column order in a DDL, composite index column order, choice-provider
options that pair with weights by index.

Set-like paths are canonicalized (sorted) before the hasher sees the config,
so authors don't have to remember to sort them and don't get a different
exp_id from a permutation of the same experiment.

The sealed archive (``configs/config_<id>.yaml``) still stores the author's
raw source bytes verbatim — canonicalization applies to the in-memory form
that goes through the hash and drives runtime iteration, not to what gets
sealed. Byte fidelity of the author's intent is preserved as provenance;
canonicalization gives the *semantic* identity a stable representation.

Extending
---------
When adding a schema field that is set-like, append its dotted path to
``SET_LIKE_PATHS``. Wildcards: ``*`` matches any dict key at that level.

The safer default when unsure is *not* to declare a field set-like.
Set-ness is a stronger claim than sequence-ness: it says "two orderings
produce the same experiment for all downstream purposes." Sequence-ness is
the safer assumption when in doubt.
"""
from copy import deepcopy
from typing import Any, List


# Dotted paths of set-like fields. `*` matches any dict key at that level.
#
# When adding to this list, include:
#   - the path
#   - a one-line justification stating why order doesn't affect the
#     experiment's semantic identity (measurements, partitions, statistics)
#
# Entries here become part of the hasher's equivalence relation.
SET_LIKE_PATHS: List[str] = [
    # `execution.engines`: the SET of engines to run. [duckdb, postgres]
    # produces the same fragments/results as [postgres, duckdb].
    "execution.engines",

    # `execution.matrix.<dim>`: the SET of symbolic values to sweep through
    # for that dimension. itertools.product over the matrix yields the same
    # cartesian product regardless of per-dim value order; partition_keys
    # are derived from that product and become canonical too (once ConfigLoader
    # applies canonicalize before _compile_scenario_config).
    "execution.matrix.*",
]


def canonicalize(config: dict) -> dict:
    """Return a deep copy of ``config`` with set-like list values sorted.

    Safe on partial or malformed configs: missing keys and non-list values
    at any registered path are skipped without error. Never mutates the
    input.
    """
    out = deepcopy(config)
    for path in SET_LIKE_PATHS:
        _apply_sort_at_path(out, path.split("."))
    return out


def _apply_sort_at_path(obj: Any, parts: List[str]) -> None:
    if not parts:
        return
    head, rest = parts[0], parts[1:]

    if head == "*":
        if not isinstance(obj, dict):
            return
        if not rest:
            # Terminal wildcard: sort every value that's a list at this level.
            # This is how "execution.matrix.*" reaches each dim's value list
            # without SET_LIKE_PATHS having to name each dim (rows, memory, …).
            for key in obj:
                _sort_in_place(obj, key)
            return
        # Non-terminal wildcard: recurse into each child.
        for key in obj:
            _apply_sort_at_path(obj[key], rest)
        return

    if not isinstance(obj, dict) or head not in obj:
        return

    if rest:
        _apply_sort_at_path(obj[head], rest)
        return

    _sort_in_place(obj, head)


def _sort_in_place(container: dict, key: str) -> None:
    """If container[key] is a list, sort it. Otherwise leave it alone."""
    target = container[key]
    if isinstance(target, list):
        try:
            container[key] = sorted(target, key=_sort_key)
        except TypeError:
            # Un-sortable heterogeneous items — leave as-is. Not expected for
            # set-like fields (typically homogeneous), but never crash.
            pass


def _sort_key(x: Any):
    """Stable key for heterogeneous lists: group by type name, then value.

    Homogeneous lists sort naturally within their type (ints numerically,
    strings lexicographically). Mixed-type lists are deterministically
    partitioned by type name — an edge case that shouldn't arise for
    matrix dims but stays defined if it does.
    """
    return (type(x).__name__, x)
