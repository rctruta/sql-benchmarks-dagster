"""Shared display metadata + paths for the figure tools (scripts/tools/plot_*.py).

Design-once: an engine's label/color/marker, and the results path, live HERE.
Every plot_*.py imports from this module, so adding an engine or restyling is a
single edit — not a copy-paste across four scripts.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Single source of truth for the results path — defined in the package, not redefined here.
from sql_benchmarks.constants import RESULTS_DIR  # noqa: E402

# engine -> (display label, hex color, marker). The ONE place to add/restyle an engine.
# Keys track sql_benchmarks.constants.KNOWN_ENGINES.
ENGINE_DISPLAY = {
    "duckdb":         ("DuckDB in-process",             "#2f6f4f", "o"),
    "quack":          ("Quack attach (ATTACH + USE)",   "#b3402a", "s"),
    "quack_pushdown": ("Quack pushdown (remote.query)", "#3b6ea5", "^"),
    "postgres":       ("PostgreSQL",                    "#7a5ea8", "D"),
    "actian":         ("Actian Vector",                 "#c98a1b", "v"),
    "typedb":         ("TypeDB",                         "#4c4c4c", "P"),
}


def style(engine: str):
    """(label, color, marker) for an engine; falls back to the raw name + default marker."""
    return ENGINE_DISPLAY.get(engine, (engine, None, "o"))


def bench_string(env: dict, engines=()) -> str:
    """One-line bench descriptor from a capsule's metadata environment.

    Lists versions only for the engines the experiment actually used — never
    hardcodes a single engine (so a Postgres-only figure won't claim 'DuckDB').
    """
    parts = [env.get("machine", ""), f"{env.get('cpu_count_logical', '?')} cores"]
    versions = [f"{e} {env[e]}" for e in engines if env.get(e)]
    tail = ", ".join(versions) if versions else (f"Python {env['python']}" if env.get("python") else "")
    return " · ".join(p for p in (*parts, tail) if p)
