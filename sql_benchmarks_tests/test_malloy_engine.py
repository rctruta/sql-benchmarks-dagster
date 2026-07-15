"""Unit tests for the malloy engine's client-side behavior (no server)."""
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from sql_benchmarks.resources.malloy_client import MalloyClient


@pytest.fixture
def client(tmp_path):
    from sql_benchmarks.resources.storage import LocalDirStore
    return MalloyClient(store=LocalDirStore(str(tmp_path / "pkg")), port=4001,
                        environment="bench", package="bench",
                        container="sbd-malloy-publisher")


@pytest.fixture
def parquet(tmp_path):
    p = tmp_path / "src.parquet"
    pq.write_table(pa.table({"x": [1, 2]}), p)
    return str(p)


def test_bulk_load_writes_parquet_and_model(client, parquet):
    client.bulk_load(parquet, "analytical_data", "small")
    pkg = client.store.root
    assert os.path.exists(os.path.join(pkg, "analytical_data_small.parquet"))
    model = open(os.path.join(pkg, "bench_small.malloy")).read()
    assert "source: analytical_data is duckdb.table('analytical_data_small.parquet')" in model


def test_bulk_load_is_idempotent_and_appends_tables(client, parquet):
    client.bulk_load(parquet, "analytical_data", "small")
    client.bulk_load(parquet, "analytical_data", "small")  # re-run: no dup
    client.bulk_load(parquet, "dim_products", "small")     # second table: appended
    model = open(os.path.join(client.store.root, "bench_small.malloy")).read()
    assert model.count("source: analytical_data") == 1
    assert model.count("source: dim_products") == 1


def test_bulk_load_rejects_unsafe_identifiers(client, parquet):
    with pytest.raises(ValueError):
        client.bulk_load(parquet, "analytical; drop", "small")
    with pytest.raises(ValueError):
        client.bulk_load(parquet, "analytical_data", "../etc")


def test_partitions_get_separate_models(client, parquet):
    client.bulk_load(parquet, "analytical_data", "small")
    client.bulk_load(parquet, "analytical_data", "large")
    assert os.path.exists(os.path.join(client.store.root, "bench_small.malloy"))
    assert os.path.exists(os.path.join(client.store.root, "bench_large.malloy"))
