#!/usr/bin/env python3
"""
ADBC vs row-based connectivity: what does the *transport* layer cost?

The same question this lab asked of DuckDB's Quack protocol, pointed at ADBC
(Arrow Database Connectivity). ODBC/JDBC/DBAPI deliver query results row by row
as language objects; an analytical consumer rebuilds them into columns. ADBC and
connectorx deliver Apache Arrow (columnar) batches directly — no per-row object,
no transpose.

FAIR BASELINE NOTE: the consumer here is **polars**, not pandas. polars is
Arrow-native, so it does NOT penalize the row-based path with a slow
materialization step the way pandas would — using pandas as the consumer would
conflate "ADBC is fast" with "pandas is slow" and rig the result. We compare the
*strongest* realistic alternatives, all landing in a polars DataFrame:
  1. psycopg2 .fetchall() -> pl.DataFrame   — the row-based floor
  2. ADBC                  -> pl (read_database_uri, engine="adbc")
  3. connectorx            -> pl (read_database_uri, engine="connectorx")

(2) and (3) are both Arrow-native; (1) is the legacy row path. The query is
SELECT-* shaped (large result) so timing isolates TRANSPORT + materialization,
not query execution (a count(*) would hide it). Warm runs, min of N reps. The
returned row count is asserted per path, so a mis-sized table can't fake a result
(it did once: LIMIT N against a smaller table silently caps — hence the check).
Compare RATIOS across benches, never absolute ms.

NOTE: exploratory connectivity benchmark, not a sealed capsule — it spins up its
own table and prints numbers; no content-addressed Experiment ID yet.

Deps (not in core requirements; install on demand):
    uv pip install adbc_driver_postgresql adbc_driver_manager connectorx psycopg2-binary
    # polars is already a lab dependency

Usage:
    python scripts/tools/adbc_transport_bench.py \
        --uri postgresql://postgres:password@localhost:5433/postgres_db \
        --rows 8000000 --sizes 100000 1000000 5000000 --reps 3
"""
import argparse
import time
import warnings

import polars as pl
import psycopg2

warnings.filterwarnings("ignore")


def _pg_params(uri: str) -> dict:
    from sqlalchemy.engine import make_url
    u = make_url(uri)
    return dict(host=u.host, port=u.port or 5432, user=u.username,
                password=u.password, dbname=u.database)


def best(fn, reps: int):
    """Min wall-clock over `reps` warm runs; returns (min_seconds, last_row_count)."""
    times, n = [], None
    for _ in range(reps):
        t = time.time()
        n = fn()
        times.append(time.time() - t)
    return min(times), n


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
    ap.add_argument("--rows", type=int, default=8_000_000, help="size of the source table")
    ap.add_argument("--sizes", type=int, nargs="+", default=[100_000, 1_000_000, 5_000_000])
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()

    pg = _pg_params(args.uri)
    print(f"Building adbc_wide: {args.rows:,} rows x 5 cols ...")
    build_table(args.uri, args.rows)

    print(f"\n{'rows':>10} {'psycopg->pl':>13} {'ADBC->pl':>10} {'connectorx->pl':>15}")
    for n in args.sizes:
        if n > args.rows:
            print(f"{n:>10,}  (skipped: exceeds table size {args.rows:,})")
            continue
        q = f"SELECT id, a, b, c, d FROM adbc_wide LIMIT {n}"

        def via_psycopg():
            c = psycopg2.connect(**pg); cc = c.cursor(); cc.execute(q)
            cols = [d[0] for d in cc.description]; rows = cc.fetchall()
            df = pl.DataFrame(rows, schema=cols, orient="row"); c.close()
            return df.height

        def via_adbc():
            return pl.read_database_uri(q, args.uri, engine="adbc").height

        def via_cx():
            return pl.read_database_uri(q, args.uri, engine="connectorx").height

        (t_pg, n_pg), (t_ad, n_ad), (t_cx, n_cx) = best(via_psycopg, args.reps), best(via_adbc, args.reps), best(via_cx, args.reps)
        assert n_pg == n_ad == n_cx == n, f"row-count mismatch: {n_pg}/{n_ad}/{n_cx} vs {n}"
        print(f"{n:>10,} {t_pg*1000:>11.0f}ms {t_ad*1000:>8.0f}ms {t_cx*1000:>13.0f}ms")


if __name__ == "__main__":
    main()
