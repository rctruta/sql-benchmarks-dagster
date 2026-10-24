"""Standalone worker process executed under a specific DuckDB version via uv.

Zero third-party dependencies beyond `duckdb`.
Executed via:
    uv run --no-project --with duckdb==<VERSION> python -m sql_benchmarks.resources.duckdb_worker <command> [options]
"""
import argparse
import json
import os
import re
import resource
import sys
import time
from typing import Dict, Any

_SAFE_IDENTIFIER = re.compile(r"^\w+$")
_SAFE_SETTING_VALUE = re.compile(r"^[A-Za-z0-9._]+$")

DUCKDB_SETTING_KEYS = frozenset({
    "threads",
    "memory_limit",
})


def _assert_safe_identifier(value: str, label: str) -> None:
    if not _SAFE_IDENTIFIER.match(value):
        raise ValueError(f"Unsafe {label}: '{value}'. Only word characters allowed.")


def _apply_engine_params(con, engine_params: Dict[str, Any]) -> None:
    for key, value in (engine_params or {}).items():
        if key not in DUCKDB_SETTING_KEYS:
            raise ValueError(
                f"Unknown duckdb engine_params key '{key}'. "
                f"Allowed: {sorted(DUCKDB_SETTING_KEYS)}"
            )
        if not _SAFE_SETTING_VALUE.match(str(value)):
            raise ValueError(f"Unsafe value for duckdb setting '{key}': {value!r}")
        con.execute(f"SET {key} = '{value}'")


def cmd_bulk_load(args: argparse.Namespace) -> None:
    import duckdb

    _assert_safe_identifier(args.table_name, "table name")
    filepath = os.path.realpath(args.filepath)

    os.makedirs(os.path.dirname(args.db_path), exist_ok=True)
    with duckdb.connect(args.db_path, read_only=False) as con:
        con.execute(
            f"CREATE OR REPLACE TABLE {args.table_name} AS SELECT * FROM read_parquet(?)",
            [filepath],
        )

    output = {
        "status": "ok",
        "action": "bulk_load",
        "table": args.table_name,
        "version": duckdb.__version__,
    }
    print(json.dumps(output))


def cmd_query(args: argparse.Namespace) -> None:
    import duckdb

    if args.sql:
        sql = args.sql
    else:
        sql = sys.stdin.read()

    engine_params = {}
    if args.engine_params:
        engine_params = json.loads(args.engine_params)

    with duckdb.connect(args.db_path, read_only=False) as con:
        _apply_engine_params(con, engine_params)

        # High-resolution CPU/wall timing
        start_time = time.perf_counter()
        con.sql(sql).fetchall()
        end_time = time.perf_counter()

        duration = end_time - start_time
        peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        output = {
            "status": "ok",
            "action": "query",
            "duration_seconds": duration,
            "version": duckdb.__version__,
            "peak_rss": peak_rss,
        }
        print(json.dumps(output))


def main() -> None:
    parser = argparse.ArgumentParser(description="DuckDB Version-Isolated Worker")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Bulk load parser
    load_parser = subparsers.add_parser("bulk_load")
    load_parser.add_argument("--db-path", required=True, help="Path to DuckDB database file")
    load_parser.add_argument("--table-name", required=True, help="Target table name")
    load_parser.add_argument("--filepath", required=True, help="Source parquet file path")

    # Query parser
    query_parser = subparsers.add_parser("query")
    query_parser.add_argument("--db-path", required=True, help="Path to DuckDB database file")
    query_parser.add_argument("--sql", default=None, help="SQL string to execute (or stdin)")
    query_parser.add_argument("--engine-params", default=None, help="JSON string of engine params")

    args = parser.parse_args()

    try:
        if args.subcommand == "bulk_load":
            cmd_bulk_load(args)
        elif args.subcommand == "query":
            cmd_query(args)
    except Exception as e:
        err_output = {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__,
        }
        print(json.dumps(err_output), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
