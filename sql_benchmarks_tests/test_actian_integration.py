import pytest
import os
from unittest.mock import MagicMock, patch, PropertyMock


@pytest.fixture
def mock_ssh_env(monkeypatch):
    """Set up environment variables for Actian EC2 connection."""
    monkeypatch.setenv("ACTIAN_EC2_HOST", "test-ec2-host.amazonaws.com")
    monkeypatch.setenv("ACTIAN_EC2_USER", "ingres")
    monkeypatch.setenv("ACTIAN_DATABASE", "benchmark_db")
    monkeypatch.setenv("ACTIAN_USER", "ingres")
    monkeypatch.setenv("ACTIAN_PASSWORD", "testpass")


def test_actian_engine_name(mock_ssh_env):
    """Verify engine returns correct name."""
    from sql_benchmarks.resources.actian import ActianEngine

    engine = ActianEngine()
    assert engine.get_engine_name() == "actian"


def test_actian_engine_requires_ec2_host():
    """Verify engine fails gracefully when EC2 host is not configured."""
    from sql_benchmarks.resources.actian import ActianEngine

    # Clear any existing env var
    with patch.dict(os.environ, {"ACTIAN_EC2_HOST": ""}, clear=False):
        engine = ActianEngine(ec2_host="")

        with pytest.raises(ValueError) as excinfo:
            engine._ensure_tunnel()

        assert "ACTIAN_EC2_HOST" in str(excinfo.value)


def test_actian_client_ssh_exec(mock_ssh_env):
    """Test SSH command execution in client."""
    from sql_benchmarks.resources.actian_client import ActianClient

    connection_params = {
        "host": "localhost",
        "port": 27832,
        "user": "ingres",
        "password": "testpass",
        "database": "benchmark_db"
    }

    ssh_params = {
        "ec2_host": "test-ec2-host",
        "ec2_user": "ingres",
        "ssh_key_path": "/path/to/key.pem",
        "remote_data_dir": "/tmp/benchmark_data",
        "vwload_path": "/opt/Actian/VectorVW/ingres/bin/vwload",
        "actian_sql_path": "/opt/Actian/VectorVW/ingres/bin/sql",
    }

    with patch("paramiko.SSHClient") as mock_ssh_class:
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client

        # Mock exec_command return
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"OK"
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        client = ActianClient(connection_params, ssh_params)
        stdout, stderr, exit_code = client._ssh_exec("echo test")

        assert exit_code == 0
        assert stdout == "OK"
        mock_client.connect.assert_called_once()


def test_actian_client_run_query(mock_ssh_env):
    """Test query execution via SSH."""
    from sql_benchmarks.resources.actian_client import ActianClient

    connection_params = {
        "host": "localhost",
        "port": 27832,
        "user": "ingres",
        "password": "testpass",
        "database": "benchmark_db"
    }

    ssh_params = {
        "ec2_host": "test-ec2-host",
        "ec2_user": "ingres",
        "ssh_key_path": "/path/to/key.pem",
        "remote_data_dir": "/tmp/benchmark_data",
        "vwload_path": "/opt/Actian/VectorVW/ingres/bin/vwload",
        "actian_sql_path": "/opt/Actian/VectorVW/ingres/bin/sql",
    }

    with patch("paramiko.SSHClient") as mock_ssh_class:
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client

        # Mock successful query execution
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"1 row"
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        client = ActianClient(connection_params, ssh_params)
        duration = client.run_query("SELECT 1", {})

        assert duration is not None
        assert duration >= 0


def test_actian_engine_clear_cache_restarts_service(mock_ssh_env):
    """Test that clear_cache issues systemctl restart via SSH."""
    from sql_benchmarks.resources.actian import ActianEngine

    with patch("paramiko.SSHClient") as mock_ssh_class:
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client

        # Mock successful restart
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        # Mock tunnel
        with patch("sshtunnel.SSHTunnelForwarder") as mock_tunnel_class:
            mock_tunnel = MagicMock()
            mock_tunnel.is_active = True
            mock_tunnel.local_bind_port = 27832
            mock_tunnel_class.return_value = mock_tunnel

            # Mock socket for _wait_for_ready
            with patch("socket.create_connection"):
                engine = ActianEngine()
                engine.clear_cache()

                # Verify systemctl restart was called
                calls = mock_client.exec_command.call_args_list
                restart_calls = [c for c in calls if "systemctl restart" in str(c)]
                assert len(restart_calls) >= 1


def test_semantic_auditor_catch_poisoned_data():
    """
    Simulates the 'Blueberry Muffin' exploit (Negative durations).
    Ensures the SemanticAuditor correctly identifies the violation.
    """
    from sql_benchmarks.utils.semantic_auditor import SemanticAuditor

    auditor = SemanticAuditor()

    # 1. VALID DATA (Metrics format)
    valid_fragment = {"metrics": {"duration_seconds": 1.5, "rows": 100}}
    result_valid = auditor.audit_fragment(valid_fragment)
    assert result_valid["success"] is True

    # 2. POISONED DATA (Negative Duration - Physical Impossibility)
    poisoned_fragment = {"metrics": {"duration_seconds": -5.0, "rows": 100}}
    result_poisoned = auditor.audit_fragment(poisoned_fragment)

    assert result_poisoned["success"] is False
    assert any("Negative duration" in v for v in result_poisoned["violations"])


def test_actian_tunnel_lifecycle(mock_ssh_env):
    """Test SSH tunnel is properly managed."""
    from sql_benchmarks.resources.actian import ActianEngine

    with patch("sshtunnel.SSHTunnelForwarder") as mock_tunnel_class:
        mock_tunnel = MagicMock()
        mock_tunnel.is_active = True
        mock_tunnel.local_bind_port = 27832
        mock_tunnel_class.return_value = mock_tunnel

        engine = ActianEngine()
        engine._ensure_tunnel()

        mock_tunnel.start.assert_called_once()

        # Cleanup
        engine.cleanup()
        mock_tunnel.stop.assert_called_once()
