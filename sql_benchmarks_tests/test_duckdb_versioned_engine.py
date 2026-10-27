"""Unit and integration tests for version-isolated DuckDB engine metrology.

Verifies:
1. DuckDBEngine facade delegating to DuckDBVersionClient when version is set.
2. DuckDBVersionClient invoking uv run subprocess workers for 1.5.3 and 2.0.0.
3. DuckDBWorker CLI bulk_load and query execution.
4. Input validation and error propagation (safe identifiers, settings allowlist).
"""
import json
import os
import subprocess
import sys
import tempfile
import pytest
from sql_benchmarks.resources.duckdb import DuckDBEngine
from sql_benchmarks.resources.duckdb_version_client import DuckDBVersionClient
from sql_benchmarks.resources.duckdb_worker import (
    _assert_safe_identifier,
    _apply_engine_params,
    DUCKDB_SETTING_KEYS,
)


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


def test_duckdb_worker_safe_identifier_validation():
    """Verify worker rejects unsafe SQL injection identifiers in table names."""
    _assert_safe_identifier("valid_table_123", "table name")
    with pytest.raises(ValueError, match="Unsafe table name"):
        _assert_safe_identifier("table; DROP TABLE users;--", "table name")
    with pytest.raises(ValueError, match="Unsafe table name"):
        _assert_safe_identifier("table with spaces", "table name")


def test_duckdb_worker_engine_params_validation():
    """Verify worker enforces setting allowlist and safe values."""
    import duckdb

    with duckdb.connect() as con:
        # Valid settings
        _apply_engine_params(con, {"threads": 2, "memory_limit": "500MB"})

        # Unknown setting must fail loudly
        with pytest.raises(ValueError, match="Unknown duckdb engine_params key"):
            _apply_engine_params(con, {"unsupported_setting": "10"})

        # Unsafe setting value must fail loudly
        with pytest.raises(ValueError, match="Unsafe value for duckdb setting"):
            _apply_engine_params(con, {"threads": "4; DROP TABLE--"})


def test_duckdb_version_client_execution():
    """Verify both 1.5.3 and 2.0.0 can bulk load parquet data and run queries in isolated workers."""
    import shutil
    from sql_benchmarks.resources.duckdb_version_client import _find_uv_bin
    if not shutil.which("uv") and _find_uv_bin() == "uv":
        pytest.skip("uv binary not available on system PATH")

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


def test_duckdb_worker_cli_query_direct():
    """Verify direct invocation of duckdb_worker via CLI subprocess."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.duckdb")

        # Test query via CLI with stdin
        cmd = [
            sys.executable,
            "-m",
            "sql_benchmarks.resources.duckdb_worker",
            "query",
            "--db-path",
            db_path,
        ]
        sql = "SELECT 42 AS num, 'hello' AS str"
        result = subprocess.run(cmd, input=sql, capture_output=True, text=True)
        assert result.returncode == 0
        payload = json.loads(result.stdout.strip())
        assert payload["status"] == "ok"
        assert payload["action"] == "query"
        assert payload["duration_seconds"] > 0
        assert "version" in payload
        assert "peak_rss" in payload
