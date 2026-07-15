"""Equivalence gate: the malloy dialect must return the same rows as duckdb.

A cross-dialect benchmark is a strawman unless the queries are semantically
identical. This script executes the analytical_wall duckdb SQL in-process and
the malloy dialect through a running Publisher (infrastructure/malloy), on the
SAME parquet file, and asserts row-for-row equality (2-decimal tolerance,
matching the queries' own ROUND(2)).

Usage:
  docker compose -f infrastructure/malloy/docker-compose.yml up -d
  python scripts/verify_malloy_equivalence.py <parquet_file> <partition_key>

Exits non-zero on any mismatch: run it before trusting any duckdb-vs-malloy
capsule, and after any edit to either dialect file.
"""
import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sql_benchmarks.resources.malloy_client import MalloyClient  # noqa: E402

SQL_DIR = os.path.join(ROOT, "sql_benchmarks", "scripts", "sql", "analytical_wall")
TABLE = "analytical_data"


def duckdb_rows(parquet: str):
    sql = open(os.path.join(SQL_DIR, "duckdb", "analytical_wall.sql")).read()
    sql = sql.replace("{{ analytical_data_table }}",
                      f"read_parquet('{parquet}')")
    con = duckdb.connect()
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def malloy_rows(parquet: str, partition_key: str):
    from sql_benchmarks.resources.storage import MountedVolumeStore
    client = MalloyClient(
        store=MountedVolumeStore(
            host_dir=os.path.join(ROOT, "data", "malloy", "bench"),
            container_dir="/publisher/publisher_data/bench/bench",
            container="sbd-malloy-publisher"),
        port=int(os.getenv("SB_MALLOY_PORT", "4001")),
        environment="bench", package="bench",
        container="sbd-malloy-publisher")
    client.bulk_load(parquet, TABLE, partition_key)
    client.restart_server()  # Publisher syncs package contents at startup
    query = open(os.path.join(SQL_DIR, "malloy", "analytical_wall.malloy")).read()
    # The harness renders {{ analytical_data_table }} per partition; here the
    # gate loaded the source under the bare table name.
    query = query.replace("{{ analytical_data_table }}", TABLE)
    return client.fetch_rows(query, partition_key)


def main():
    parquet, partition_key = sys.argv[1], sys.argv[2]
    d_rows = duckdb_rows(os.path.realpath(parquet))
    m_rows = malloy_rows(parquet, partition_key)

    if len(d_rows) != len(m_rows):
        sys.exit(f"FAIL: row count {len(d_rows)} (duckdb) != {len(m_rows)} (malloy)")

    mismatches = 0
    for i, (d, m) in enumerate(zip(d_rows, m_rows)):
        for k, dv in d.items():
            mv = m.get(k)
            if isinstance(dv, (int, float)) and isinstance(mv, (int, float)):
                if abs(float(dv) - float(mv)) > 0.01:
                    print(f"row {i} col {k}: duckdb={dv} malloy={mv}")
                    mismatches += 1
            elif str(dv) != str(mv):
                print(f"row {i} col {k}: duckdb={dv!r} malloy={mv!r}")
                mismatches += 1

    if mismatches:
        sys.exit(f"FAIL: {mismatches} mismatched cells across {len(d_rows)} rows")
    print(f"PASS: {len(d_rows)} rows identical across dialects "
          f"(tolerance 0.01, matching ROUND(2))")


if __name__ == "__main__":
    main()
