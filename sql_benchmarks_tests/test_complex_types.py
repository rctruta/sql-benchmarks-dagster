"""Complex-type generation: json_blob provider + Postgres JSONB DDL override.

Unit tests always run. The integration test loads into a live Postgres and is
skipped when none is reachable (CI without Docker, etc.)."""
import json
import os
import tempfile

import numpy as np
import polars as pl
import pytest

from sql_benchmarks.utils.providers import generate_json_blob

PG_URI = "postgresql://postgres:password@localhost:5433/postgres_db"


# ---------- unit ----------
def test_json_blob_emits_valid_json():
    np.random.seed(0)
    blobs = generate_json_blob(50, keys=3)
    assert len(blobs) == 50
    objs = [json.loads(b) for b in blobs]            # raises on malformed JSON
    assert all({"k0", "k1", "k2", "score", "cat", "tags"} <= set(o) for o in objs)
    assert all(isinstance(o["tags"], list) for o in objs)   # genuinely nested


def test_json_blob_keys_param_controls_width():
    np.random.seed(0)
    o = json.loads(generate_json_blob(1, keys=5)[0])
    assert {f"k{i}" for i in range(5)} <= set(o)


# ---------- integration (needs live Postgres) ----------
def _pg_up() -> bool:
    try:
        import psycopg2
        psycopg2.connect(host="localhost", port=5433, user="postgres",
                          password="password", dbname="postgres_db",
                          connect_timeout=2).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _pg_up(), reason="no live Postgres on :5433")
def test_json_blob_lands_as_real_jsonb():
    from sqlalchemy import text
    from sql_benchmarks.resources.postgres_client import PostgresClient
    np.random.seed(1)
    df = pl.DataFrame({"id": list(range(500)),
                       "payload": [str(x) for x in generate_json_blob(500)]})
    path = os.path.join(tempfile.mkdtemp(), "j.parquet")
    df.write_parquet(path)
    table_def = {"columns": [{"name": "id", "provider": "sequence"},
                             {"name": "payload", "provider": "json_blob", "type": "jsonb"}]}
    cli = PostgresClient(PG_URI)
    cli.bulk_load(path, "jsonb_pytest", table_def=table_def)
    with cli.engine.connect() as c:
        dtype = c.execute(text("select data_type from information_schema.columns "
                               "where table_name='jsonb_pytest' and column_name='payload'")).fetchone()[0]
        # jsonb operator must work => it's genuinely jsonb, not TEXT
        hits = c.execute(text("select count(*) from jsonb_pytest where payload->>'cat'='alpha'")).fetchone()[0]
        c.execute(text("drop table if exists jsonb_pytest")); c.commit()
    assert dtype == "jsonb"
    assert hits == 125           # 500 rows, 4 categories, round-robin
