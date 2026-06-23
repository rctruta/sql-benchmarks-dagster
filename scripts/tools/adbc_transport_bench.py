#!/usr/bin/env python3
"""
ADBC vs row-based connectivity: what does the *transport* layer cost?

The same question this lab asked of DuckDB's Quack protocol, pointed at ADBC
(Arrow Database Connectivity). ODBC/JDBC/DBAPI deliver query results row by row
as Python objects; an analytical consumer then rebuilds them into columns.
ADBC delivers results as Apache Arrow (columnar) batches directly — no
per-row Python object, no transpose. This measures the gap on a real result set.

Three client paths fetch the SAME query result into analytical form:
  1. psycopg2 .fetchall()      — raw row tuples (the row-based floor)
  2. pandas.read_sql()         — rows -> DataFrame (what analysts actually write)
  3. ADBC .fetch_arrow_table() — columnar Arrow, direct

Methodology: the query is SELECT-* shaped (large result) so the timing isolates
TRANSPORT + materialization, not query execution (a count(*) would hide it).
Warm runs, min of N reps. Compare RATIOS across benches, never absolute ms.

NOTE: this is an exploratory connectivity benchmark, not a sealed capsule — it
spins up its own table and prints numbers; it does not (yet) produce a
content-addressed Experiment ID. Promote to a harness experiment to seal it.

Deps (not in core requirements; install on demand):
    uv pip install adbc_driver_postgresql adbc_driver_manager pyarrow psycopg2-binary

Usage:
    python scripts/tools/adbc_transport_bench.py \
        --uri postgresql://postgres:password@localhost:5433/postgres_db \
        --rows 5000000 --sizes 100000 1000000 5000000 --reps 2
"""
import argparse
import time
import warnings

import pandas as pd
import psycopg2
import adbc_driver_postgresql.dbapi as pg_adbc

warnings.filterwarnings("ignore")


def _pg_params(uri: str) -> dict:
    from sqlalchemy.engine import make_url
    u = make_url(uri)
    return dict(host=u.host, port=u.port or 5432, user=u.username,
                password=u.password, dbname=u.database)


def best(fn, reps: int) -> float:
    """Min wall-clock over `reps` warm runs (isolates transport from cold noise)."""
    times = []
    for _ in range(reps):
        t = time.time()
        fn()
        times.append(time.time() - t)
    return min(times)


def build_table(uri: str, rows: int) -> None:
    conn = psycopg2.connect(**_pg_params(uri))
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS adbc_wide;")
    cur.execute(f"""
        CREATE TABLE adbc_wide AS
        SELECT i AS id, (i % 1000) AS a, (random() * 100)::float8 AS b,
               md5(i::text) AS c, (random() * 1e6)::float8 AS d
        FROM generate_series(1, {rows}) i;
    """)
    cur.execute("ANALYZE adbc_wide;")
    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--uri", default="postgresql://postgres:password@localhost:5433/postgres_db")
    ap.add_argument("--rows", type=int, default=5_000_000, help="size of the source table")
    ap.add_argument("--sizes", type=int, nargs="+", default=[100_000, 1_000_000, 5_000_000])
    ap.add_argument("--reps", type=int, default=2)
    args = ap.parse_args()

    pg = _pg_params(args.uri)
    print(f"Building adbc_wide: {args.rows:,} rows x 5 cols ...")
    build_table(args.uri, args.rows)

    hdr = f"{'rows':>10} {'psycopg rows':>14} {'pandas.read_sql':>17} {'ADBC->Arrow':>13} {'ADBC vs pandas':>16}"
    print("\n" + hdr)
    for n in args.sizes:
        q = f"SELECT id, a, b, c, d FROM adbc_wide LIMIT {n}"

        def via_psycopg():
            c = psycopg2.connect(**pg); cc = c.cursor()
            cc.execute(q); cc.fetchall(); c.close()

        def via_pandas():
            c = psycopg2.connect(**pg)
            pd.read_sql(q, c); c.close()

        def via_adbc():
            c = pg_adbc.connect(args.uri); cc = c.cursor()
            cc.execute(q); cc.fetch_arrow_table(); c.close()

        t_pg = best(via_psycopg, args.reps)
        t_pd = best(via_pandas, args.reps)
        t_ad = best(via_adbc, args.reps)
        print(f"{n:>10,} {t_pg*1000:>12.0f}ms {t_pd*1000:>15.0f}ms {t_ad*1000:>11.0f}ms {t_pd/t_ad:>14.2f}x")


if __name__ == "__main__":
    main()
