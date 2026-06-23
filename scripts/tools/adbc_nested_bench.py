#!/usr/bin/env python3
"""
Nested-type transport: where does columnar (ADBC/connectorx) pay off vs row-based?

Extends adbc_transport_bench to COMPLEX types. The conventional worry is that
columnar/Arrow drivers choke building nested structures (jsonb -> struct/string,
postgres array -> Arrow list). This measures it on REAL Postgres jsonb + int[]
columns (built server-side, so there's no client-serialization confound), pulling
each column set into a polars DataFrame three ways:

  1. psycopg2 .fetchall() -> pl.DataFrame   — row-based (a Python dict per jsonb,
                                               a Python list per array, per row)
  2. ADBC                  -> pl (read_database_uri, engine="adbc")
  3. connectorx            -> pl (read_database_uri, engine="connectorx")

Finding (local Postgres, see the article): the Arrow advantage is modest on
primitives (~1.5x) but *widens to ~5-8x on nested types* — because the row path
pays to materialize nested Python objects while Arrow-native builds nested Arrow
columns in C. It is the row path that falls off the cliff on nesting, not Arrow.
A driver that can't handle a nested type is recorded as DNF (a finding), not hidden.

Deps:  uv pip install adbc_driver_postgresql adbc_driver_manager connectorx psycopg2-binary
       (polars is already a lab dependency)

Usage:
    python scripts/tools/adbc_nested_bench.py \
        --uri postgresql://postgres:password@localhost:5433/postgres_db \
        --rows 2000000 --sizes 1000000 2000000 --reps 3
"""
import argparse
import time

import polars as pl
import psycopg2


def _pg(uri):
    from sqlalchemy.engine import make_url
    u = make_url(uri)
    return dict(host=u.host, port=u.port or 5432, user=u.username, password=u.password, dbname=u.database)


def best(fn, reps):
    times = []
    for _ in range(reps):
        t = time.time()
        try:
            fn()
        except Exception as e:                       # a driver that can't do the type => DNF (finding)
            return None, f"DNF ({type(e).__name__})"
        times.append(time.time() - t)
    return min(times), None


def build(uri, rows):
    conn = psycopg2.connect(**_pg(uri)); conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS nested_wide;")
    cur.execute(f"""
        CREATE TABLE nested_wide AS SELECT
          i AS id,
          md5(i::text) AS label,
          jsonb_build_object('v', i % 1000, 'cat', (ARRAY['a','b','c','d'])[1 + i % 4],
                             'tags', ARRAY[i % 10, (i / 10) % 10]) AS payload,
          ARRAY[i % 10, (i / 10) % 10, (i / 100) % 10] AS tags
        FROM generate_series(1, {rows}) i;
    """)
    cur.execute("ANALYZE nested_wide;"); conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--uri", default="postgresql://postgres:password@localhost:5433/postgres_db")
    ap.add_argument("--rows", type=int, default=2_000_000)
    ap.add_argument("--sizes", type=int, nargs="+", default=[1_000_000, 2_000_000])
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()
    pg = _pg(args.uri)

    print(f"Building nested_wide: {args.rows:,} rows (id, label, jsonb payload, int[] tags) ...")
    build(args.uri, args.rows)

    def via_psycopg(q):
        c = psycopg2.connect(**pg); k = c.cursor(); k.execute(q)
        cols = [d[0] for d in k.description]; rows = k.fetchall()
        pl.DataFrame(rows, schema=cols, orient="row"); c.close()

    def via_adbc(q): pl.read_database_uri(q, args.uri, engine="adbc")
    def via_cx(q):   pl.read_database_uri(q, args.uri, engine="connectorx")

    col_sets = [("primitives", "id,label"), ("+jsonb", "id,label,payload"),
                ("+int[]", "id,label,tags"), ("jsonb+int[]", "id,label,payload,tags")]
    print(f"\n{'columns':<14}{'rows':>10}{'psycopg->pl':>14}{'ADBC->pl':>12}{'connectorx->pl':>16}")
    for name, sel in col_sets:
        for n in args.sizes:
            if n > args.rows:
                continue
            q = f"SELECT {sel} FROM nested_wide LIMIT {n}"
            def fmt(pair):
                t, dnf = pair
                return dnf if dnf else f"{t*1000:.0f}ms"
            tp = best(lambda: via_psycopg(q), args.reps)
            ta = best(lambda: via_adbc(q), args.reps)
            tx = best(lambda: via_cx(q), args.reps)
            print(f"{name:<14}{n:>10,}{fmt(tp):>14}{fmt(ta):>12}{fmt(tx):>16}")


if __name__ == "__main__":
    main()
