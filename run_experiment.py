"""Thin shim kept so `./run.sh` (and existing muscle memory) keep working.
The implementation lives in sql_benchmarks.cli and is also exposed as the
`sqlbench` console script after `pip install`.
"""
from sql_benchmarks.cli import main, resolve_targets, _is_safe_path  # noqa: F401

if __name__ == "__main__":
    main()
