import pytest
from unittest.mock import patch, MagicMock, call
from sqlalchemy import text
from sql_benchmarks.resources.postgres_client import PostgresClient, PG_SETTING_KEYS

TEST_CONN = "postgresql://postgres:password@localhost:5432/postgres"


@pytest.fixture
def mock_pg_conn():
    """Patches create_engine and yields the mock connection object."""
    with patch("sql_benchmarks.resources.postgres_client.create_engine") as mock_create:
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_create.return_value = mock_engine
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        yield mock_conn


# ---------------------------------------------------------------------------
# Module-level constant
# ---------------------------------------------------------------------------

def test_pg_setting_keys_exported():
    """PG_SETTING_KEYS is a module-level frozenset, not buried in the class."""
    assert isinstance(PG_SETTING_KEYS, frozenset)
    assert "work_mem" in PG_SETTING_KEYS
    assert "max_parallel_workers_per_gather" in PG_SETTING_KEYS


def test_pg_setting_keys_matches_class_constant():
    """Class _ALLOWED_PG_SETTINGS is identical to the module constant."""
    assert PostgresClient._ALLOWED_PG_SETTINGS == PG_SETTING_KEYS


# ---------------------------------------------------------------------------
# run_query interface
# ---------------------------------------------------------------------------

def test_run_query_applies_pg_settings_as_set_commands(mock_pg_conn):
    """Each pg_setting is issued as a parameterised SET command before the query."""
    client = PostgresClient(connection_string=TEST_CONN)
    pg_settings = {"work_mem": "256MB", "max_parallel_workers_per_gather": 4}

    client.run_query(sql="SELECT 1", pg_settings=pg_settings)

    executed = mock_pg_conn.execute.call_args_list
    set_calls = [(str(c.args[0]), c.args[1]) for c in executed if "SET" in str(c.args[0])]

    assert ("SET work_mem = :val", {"val": "256MB"}) in set_calls
    assert ("SET max_parallel_workers_per_gather = :val", {"val": "4"}) in set_calls


def test_run_query_executes_sql_after_settings(mock_pg_conn):
    """The benchmark SQL is executed after all SET commands."""
    client = PostgresClient(connection_string=TEST_CONN)
    sql = "SELECT count(*) FROM orders"

    client.run_query(sql=sql, pg_settings={"work_mem": "64MB"})

    executed = [str(c.args[0]) for c in mock_pg_conn.execute.call_args_list]
    set_index = executed.index("SET work_mem = :val")
    sql_index = executed.index(sql)
    assert sql_index > set_index


def test_run_query_no_pg_settings_executes_sql_only(mock_pg_conn):
    """With no pg_settings, only the benchmark SQL is executed — no SET commands."""
    client = PostgresClient(connection_string=TEST_CONN)

    client.run_query(sql="SELECT 1")

    executed = [str(c.args[0]) for c in mock_pg_conn.execute.call_args_list]
    assert all("SET" not in s for s in executed)
    assert "SELECT 1" in executed


def test_run_query_rejects_non_allowlisted_key(mock_pg_conn):
    """A pg_setting key not in PG_SETTING_KEYS raises ValueError — no silent pass-through."""
    client = PostgresClient(connection_string=TEST_CONN)

    with pytest.raises(ValueError, match="not in the allowlist"):
        client.run_query(sql="SELECT 1", pg_settings={"shared_buffers": "1GB"})


def test_run_query_returns_float_duration(mock_pg_conn):
    """run_query returns elapsed wall-clock time as a float."""
    client = PostgresClient(connection_string=TEST_CONN)

    with patch("time.time", side_effect=[0.0, 1.5]):
        duration = client.run_query(sql="SELECT 1")

    assert duration == pytest.approx(1.5)


def test_run_query_accepts_partition_key_without_using_it(mock_pg_conn):
    """partition_key is accepted for interface symmetry but has no effect."""
    client = PostgresClient(connection_string=TEST_CONN)

    with patch("time.time", side_effect=[0.0, 0.1]):
        duration = client.run_query(sql="SELECT 1", partition_key="medium__work_mem_64MB")

    assert duration == pytest.approx(0.1)
