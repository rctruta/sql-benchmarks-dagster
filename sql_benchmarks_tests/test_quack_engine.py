"""
Tests for the Quack engine (DuckDB client-server protocol).

The server subprocess and duckdb connections are mocked throughout — these
tests cover lifecycle ordering, delegation, dialect reuse, and fail-fast
token validation. Real protocol behavior is verified by the e2e experiment
(quack_vs_duckdb.yaml).
"""
import os
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from sql_benchmarks.resources.quack import QuackEngine
from sql_benchmarks.resources.quack_client import QuackClient, _SERVERS
from sql_benchmarks.utils.common import get_engine_sql_dialect


@pytest.fixture(autouse=True)
def clean_server_registry():
    _SERVERS.clear()
    yield
    _SERVERS.clear()


# ---------------------------------------------------------------------------
# Dialect reuse: quack executes the duckdb scenario directory
# ---------------------------------------------------------------------------

def test_quack_dialect_is_duckdb():
    assert get_engine_sql_dialect("quack") == "duckdb"


def test_other_engines_keep_their_own_dialect():
    for name in ("duckdb", "postgres", "actian", "typedb"):
        assert get_engine_sql_dialect(name) == name


# ---------------------------------------------------------------------------
# Token validation: fail fast, never interpolate junk into SQL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_token", ["", "short", "has space00", "quote'inject00"])
def test_client_rejects_unsafe_tokens(bad_token):
    with pytest.raises(ValueError, match="token"):
        QuackClient(data_folder="/tmp/q", token=bad_token)


def test_client_accepts_safe_token():
    client = QuackClient(data_folder="/tmp/q", token="sb-local-quack-token")
    assert client.port == 9494


# ---------------------------------------------------------------------------
# Facade delegation
# ---------------------------------------------------------------------------

def test_engine_delegates_run_query():
    with patch("sql_benchmarks.resources.quack.QuackClient") as MockClient, \
         patch("sql_benchmarks.resources.quack.thrash_os_cache") as mock_thrash:
        mock_instance = MockClient.return_value
        mock_instance.run_query.return_value = 1.5

        engine = QuackEngine(data_folder="/tmp/q")
        result = engine.run_query(sql="SELECT 1", partition_key="tiny",
                                  engine_params={"server_threads": 2})

        mock_thrash.assert_called_once()
        MockClient.assert_called_once_with(
            data_folder="/tmp/q", port=9494, token="sb-local-quack-token",
            pushdown=False, arrow=False,
        )
        mock_instance.run_query.assert_called_once_with(
            sql="SELECT 1", partition_key="tiny",
            engine_params={"server_threads": 2}
        )
        assert result == 1.5


def test_engine_delegates_bulk_load():
    with patch("sql_benchmarks.resources.quack.QuackClient") as MockClient:
        engine = QuackEngine(data_folder="/tmp/q")
        engine.bulk_load(filepath="/tmp/x.parquet", table_name="t_tiny", partition_key="tiny")
        MockClient.return_value.bulk_load.assert_called_once_with(
            "/tmp/x.parquet", "t_tiny", "tiny", None
        )


def test_engine_name():
    assert QuackEngine(data_folder="/tmp/q").get_engine_name() == "quack"


# ---------------------------------------------------------------------------
# Client lifecycle ordering
# ---------------------------------------------------------------------------

def test_bulk_load_stops_server_before_loading():
    """The server holds the db file open — loading must stop it first."""
    client = QuackClient(data_folder="/tmp/q", token="sb-local-quack-token")
    call_order = []
    with patch.object(client, "stop_server", side_effect=lambda: call_order.append("stop")), \
         patch.object(client._duck, "bulk_load", side_effect=lambda *a: call_order.append("load")):
        client.bulk_load("/tmp/x.parquet", "t_tiny", "tiny")
    assert call_order == ["stop", "load"]


def test_run_query_cold_starts_and_always_stops_server():
    """Sequence: stop (cold) → start → measure → stop, even on success."""
    client = QuackClient(data_folder="/tmp/q", token="sb-local-quack-token")
    order = []
    fake_proc = MagicMock()
    fake_con = MagicMock()
    fake_con.sql.return_value.fetchall.return_value = [(1,)]

    with patch.object(client, "stop_server", side_effect=lambda: order.append("stop")), \
         patch.object(client, "_start_server", side_effect=lambda p: order.append("start") or fake_proc), \
         patch.object(client, "_attach_with_retry", side_effect=lambda c, p: order.append("attach")), \
         patch("sql_benchmarks.resources.quack_client.duckdb.connect", return_value=fake_con):
        duration = client.run_query(sql="SELECT 1", partition_key="tiny")

    assert order == ["stop", "start", "attach", "stop"]
    assert duration is not None and duration >= 0
    fake_con.execute.assert_any_call("USE remote")
    fake_con.close.assert_called_once()


def test_pushdown_wraps_sql_in_remote_query_and_escapes_quotes():
    """Pushdown mode ships SQL text server-side; single quotes are doubled."""
    client = QuackClient(data_folder="/tmp/q", token="sb-local-quack-token",
                         pushdown=True)
    fake_con = MagicMock()
    fake_con.sql.return_value.fetchall.return_value = [(1,)]

    with patch.object(client, "stop_server"), \
         patch.object(client, "_start_server", return_value=MagicMock()), \
         patch.object(client, "_attach_with_retry"), \
         patch("sql_benchmarks.resources.quack_client.duckdb.connect", return_value=fake_con):
        client.run_query(sql="SELECT * FROM t WHERE region = 'North'", partition_key="tiny")

    (wrapped,), _ = fake_con.sql.call_args
    assert wrapped == "FROM remote.query('SELECT * FROM t WHERE region = ''North''')"
    # attach-mode catalog switch must NOT happen in pushdown mode
    assert not any(c.args == ("USE remote",) for c in fake_con.execute.call_args_list)


def test_attach_mode_uses_remote_catalog_not_remote_query():
    client = QuackClient(data_folder="/tmp/q", token="sb-local-quack-token")
    fake_con = MagicMock()
    fake_con.sql.return_value.fetchall.return_value = [(1,)]

    with patch.object(client, "stop_server"), \
         patch.object(client, "_start_server", return_value=MagicMock()), \
         patch.object(client, "_attach_with_retry"), \
         patch("sql_benchmarks.resources.quack_client.duckdb.connect", return_value=fake_con):
        client.run_query(sql="SELECT 1", partition_key="tiny")

    fake_con.execute.assert_any_call("USE remote")
    (passed,), _ = fake_con.sql.call_args
    assert passed == "SELECT 1"


def test_engine_passes_pushdown_flag_to_client():
    with patch("sql_benchmarks.resources.quack.QuackClient") as MockClient, \
         patch("sql_benchmarks.resources.quack.thrash_os_cache"):
        engine = QuackEngine(data_folder="/tmp/q", port=9495, pushdown=True)
        engine.run_query(sql="SELECT 1", partition_key="tiny")
        MockClient.assert_called_once_with(
            data_folder="/tmp/q", port=9495, token="sb-local-quack-token",
            pushdown=True, arrow=False,
        )


def test_not_implemented_exception_records_dnf_not_crash():
    """Quack beta capability gaps (e.g. multi-scan joins in attach mode)
    return None so the factory records a DNF fragment — same contract as
    the TypeDB stack-overflow precedent. Other errors must still raise."""
    client = QuackClient(data_folder="/tmp/q", token="sb-local-quack-token")
    fake_con = MagicMock()
    fake_con.sql.side_effect = duckdb.NotImplementedException(
        "Multiple streaming scans ... not currently supported"
    )

    with patch.object(client, "stop_server") as mock_stop, \
         patch.object(client, "_start_server", return_value=MagicMock()), \
         patch.object(client, "_attach_with_retry"), \
         patch("sql_benchmarks.resources.quack_client.duckdb.connect", return_value=fake_con):
        result = client.run_query(sql="SELECT ... 3-way join ...", partition_key="small")

    assert result is None
    assert mock_stop.call_count >= 2  # pre-start stop + finally cleanup


def test_run_query_stops_server_even_on_failure():
    client = QuackClient(data_folder="/tmp/q", token="sb-local-quack-token")
    stops = []
    fake_con = MagicMock()
    fake_con.sql.side_effect = RuntimeError("boom")

    with patch.object(client, "stop_server", side_effect=lambda: stops.append(1)), \
         patch.object(client, "_start_server", return_value=MagicMock()), \
         patch.object(client, "_attach_with_retry"), \
         patch("sql_benchmarks.resources.quack_client.duckdb.connect", return_value=fake_con):
        with pytest.raises(RuntimeError, match="boom"):
            client.run_query(sql="SELECT 1", partition_key="tiny")

    assert len(stops) == 2  # cold-start stop + finally stop
    fake_con.close.assert_called_once()
