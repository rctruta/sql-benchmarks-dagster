"""Tests for version-isolated DuckDB engine metrology."""
import os
import tempfile
import pytest
from sql_benchmarks.resources.duckdb import DuckDBEngine
from sql_benchmarks.resources.duckdb_version_client import DuckDBVersionClient


def test_duckdb_version_engine_facade():
    """Verify DuckDBEngine correctly instantiates DuckDBVersionClient when version is configured."""
    engine_15 = DuckDBEngine(
        data_folder="/tmp/data_15",
        version="1.5.3",
        engine_name="duckdb_1_5",
    )
    assert engine_15.get_engine_name() == "duckdb_1_5"
    client_15 = engine_15._get_client()
    assert isinstance(client_15, DuckDBVersionClient)
    assert client_15.version == "1.5.3"
    assert client_15.data_folder == "/tmp/data_15"

    engine_20 = DuckDBEngine(
        data_folder="/tmp/data_20",
        version="2.0.0",
        engine_name="duckdb_2_0",
    )
    assert engine_20.get_engine_name() == "duckdb_2_0"
    client_20 = engine_20._get_client()
    assert isinstance(client_20, DuckDBVersionClient)
    assert client_20.version == "2.0.0"


def test_duckdb_version_client_execution():
    """Verify both 1.5.3 and 2.0.0 can bulk load parquet data and run queries in isolated workers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a small parquet file
        parquet_path = os.path.join(tmpdir, "sample.parquet")
        import duckdb
        with duckdb.connect() as con:
            con.execute(
                f"COPY (SELECT range AS id, range * 10 AS value FROM range(5000)) TO '{parquet_path}' (FORMAT PARQUET)"
            )

        # Test both engine versions
        for version in ["1.5.3", "2.0.0"]:
            data_folder = os.path.join(tmpdir, f"duckdb_{version.replace('.', '_')}")
            client = DuckDBVersionClient(data_folder=data_folder, version=version)

            # 1. Bulk load
            client.bulk_load(
                filepath=parquet_path,
                target_table_name="sample_tbl",
                partition_key="p1",
            )

            db_path = client._get_db_path("p1")
            assert os.path.exists(db_path), f"DB file was not created for version {version}"

            # 2. Run query with engine params
            duration = client.run_query(
                sql="SELECT count(*), avg(value) FROM sample_tbl",
                partition_key="p1",
                engine_params={"threads": 2, "memory_limit": "500MB"},
            )

            assert duration is not None
            assert duration > 0.0, f"Query duration should be positive for {version}"
