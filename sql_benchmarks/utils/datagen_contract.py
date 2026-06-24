"""Datagen↔reality contract: verify that generated data matches what the
config DECLARED, instead of merely profiling whatever was produced.

Two checks, kept separate because they run at different stages and against
different sources of truth:

  1. verify_stats_against_config(table_def, stats)
     Staging-frame contract. For each declared column: does the observed
     polars dtype match what the provider must produce, and does the observed
     null rate match the declared null_probability? Pure — no DB needed.

  2. verify_pg_schema(table_def, pg_columns)
     Loaded-schema contract. For each column carrying an explicit `type:`
     override (e.g. jsonb, integer[]): did Postgres actually store it as that
     type? Verified against live information_schema, not the staging stats —
     this is the gap that let "stats say String / Postgres has jsonb" go
     unnoticed.

Both return a list of human-readable violation strings (empty == clean).
Callers decide whether to raise; the lab's policy is fail-fast.

Coverage is deliberately CONSERVATIVE: a provider whose staging dtype is
data-dependent (choice, zipf_edges) is reported as skipped, never failed —
a false PASS we can tighten later beats a false FAILURE that erodes trust.
"""
from typing import Any, Dict, List, Optional, Tuple

# Provider -> the polars dtype string it MUST produce in the staging frame,
# exactly as data_quality records it (str(df[col].dtype)). Only providers with
# a single deterministic dtype are listed; others are skipped (see below).
PROVIDER_EXPECTED_DTYPE: Dict[str, str] = {
    "sequence": "Int64",
    "random_int": "Int64",
    "random_float": "Float64",
    "foreign_key": "Int64",
    "foreign key": "Int64",      # registry alias
    "text_concat": "String",
    "json_blob": "String",       # emitted as JSON text; type: jsonb is a DB-only override
    "int_array": "String",       # emitted as array literal text; type: integer[] is DB-only
}

# Providers whose staging dtype depends on config/data, so we can't assert it
# without re-deriving the data. Recorded as skipped, never failed.
_DTYPE_UNVERIFIABLE = {"choice", "zipf_edges"}

# Only check null rate on partitions large enough for the observed fraction to
# be meaningful, and allow this much absolute drift from the declared rate.
_NULL_MIN_ROWS = 50
_NULL_ABS_TOLERANCE = 0.05


def verify_stats_against_config(
    table_def: Dict[str, Any],
    stats: Dict[str, Any],
) -> Tuple[List[str], List[str]]:
    """Return (violations, skipped) comparing declared columns to observed stats.

    `stats` is the data_quality profile: {"rows": int, "columns": {name: {dtype,
    null_percent, ...}}}. `table_def` is the raw config table dict with a
    "columns" list of {name, provider, type?, null_probability?}.
    """
    violations: List[str] = []
    skipped: List[str] = []

    declared = {c["name"]: c for c in table_def.get("columns", [])
                if isinstance(c, dict) and "name" in c}
    observed_cols = stats.get("columns", {})
    rows = stats.get("rows", 0)

    for name, col in declared.items():
        if name not in observed_cols:
            violations.append(
                f"column '{name}' declared in config but absent from generated data"
            )
            continue

        obs = observed_cols[name]
        provider = col.get("provider")

        # --- dtype contract ---
        if provider in _DTYPE_UNVERIFIABLE:
            skipped.append(f"{name}: dtype ({provider} is data-dependent)")
        elif provider in PROVIDER_EXPECTED_DTYPE:
            expected = PROVIDER_EXPECTED_DTYPE[provider]
            actual = obs.get("dtype")
            if actual != expected:
                violations.append(
                    f"column '{name}' (provider {provider}): expected staging "
                    f"dtype {expected}, observed {actual}"
                )
        else:
            skipped.append(f"{name}: dtype (provider '{provider}' has no declared expectation)")

        # --- null-rate contract (only literal float probabilities, large N) ---
        declared_null = col.get("null_probability", 0.0)
        if isinstance(declared_null, (int, float)) and rows >= _NULL_MIN_ROWS:
            observed_null = obs.get("null_percent", 0.0)
            if abs(observed_null - float(declared_null)) > _NULL_ABS_TOLERANCE:
                violations.append(
                    f"column '{name}': declared null_probability {declared_null}, "
                    f"observed null_percent {observed_null:.4f} "
                    f"(tolerance {_NULL_ABS_TOLERANCE})"
                )
        elif isinstance(declared_null, str):
            skipped.append(f"{name}: null rate (probability is a variable reference)")

    return violations, skipped


def expected_pg_type(declared: str) -> Tuple[str, Optional[str]]:
    """Map a config `type:` string to the (data_type, udt_name) Postgres reports
    in information_schema.columns. udt_name is None when we don't pin it.

    Arrays report data_type 'ARRAY'; the element type lives in udt_name
    ('_int4' for integer[]). Scalars report the normalized type name.
    """
    t = declared.strip().lower()
    # base name -> Postgres array udt_name
    _array_udt = {"integer": "_int4", "int": "_int4", "int4": "_int4",
                  "bigint": "_int8", "int8": "_int8", "text": "_text"}
    if t.endswith("[]"):
        base = t[:-2].strip()
        return "ARRAY", _array_udt.get(base)  # None udt => element type not pinned
    _scalar = {"int": "integer", "int4": "integer", "integer": "integer",
               "int8": "bigint", "bigint": "bigint"}
    return _scalar.get(t, t), None


def verify_pg_schema(
    table_def: Dict[str, Any],
    pg_columns: Dict[str, Dict[str, str]],
) -> List[str]:
    """Return violations comparing each `type:`-override column to the LIVE
    Postgres schema. `pg_columns` maps column_name -> {"data_type", "udt_name"}
    (from information_schema). Only override columns are checked — inferred
    columns are the engine's business, not a declared contract.
    """
    violations: List[str] = []
    for col in table_def.get("columns", []):
        if not (isinstance(col, dict) and col.get("type")):
            continue
        name = col["name"]
        if name not in pg_columns:
            violations.append(
                f"column '{name}' declares type '{col['type']}' but is absent "
                f"from the loaded Postgres table"
            )
            continue
        want_dt, want_udt = expected_pg_type(col["type"])
        got = pg_columns[name]
        got_dt = (got.get("data_type") or "").lower()
        if got_dt != want_dt.lower():
            violations.append(
                f"column '{name}': declared type '{col['type']}' expects Postgres "
                f"data_type '{want_dt}', loaded as '{got.get('data_type')}'"
            )
        elif want_udt is not None and got.get("udt_name") != want_udt:
            violations.append(
                f"column '{name}': declared type '{col['type']}' expects udt "
                f"'{want_udt}', loaded as '{got.get('udt_name')}'"
            )
    return violations
