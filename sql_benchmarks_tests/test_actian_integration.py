import pytest
from unittest.mock import MagicMock, patch
from sql_benchmarks.resources.actian import ActianEngine
from sql_benchmarks.resources.actian_client import ActianClient

@pytest.fixture
def mock_actian_native():
    with patch("sql_benchmarks.resources.actian_client.connection", create=True) as mock_conn:
        # We need to mock the internal import 'import actian.native as actian'
        with patch("sys.modules", {"actian.native": MagicMock()}) as mock_modules:
            import actian.native as actian
            yield actian

def test_actian_engine_name():
    engine = ActianEngine(container_name="test")
    assert engine.get_engine_name() == "actian"

def test_actian_client_run_query_mock():
    # Setup mock manually for Method-level import
    mock_actian = MagicMock()
    with patch.dict("sys.modules", {"actian": mock_actian, "actian.native": mock_actian}):
        mock_conn_obj = MagicMock()
        mock_actian.connect.return_value = mock_conn_obj
        mock_cursor = mock_conn_obj.cursor.return_value
        
        # Execute
        client = ActianClient({"host": "localhost", "port": 27832, "user": "u", "password": "p", "database": "d"})
        duration = client.run_query("SELECT 1", {})
        
        # Verify
        assert duration is not None
        mock_cursor.execute.assert_called_with("SELECT 1")
        mock_conn_obj.close.assert_called()

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

def test_remote_host_redirection():
    # Verify that ActianEngine respects a remote host setting
    engine = ActianEngine(host="10.0.0.1", port=1234)
    client = engine._get_client()
    assert client.connection_params["host"] == "10.0.0.1"
    assert client.connection_params["port"] == 1234

def test_actian_engine_clear_cache_lifecycle():
    # Setup mock docker
    with patch("docker.from_env") as mock_docker:
        mock_container = MagicMock()
        mock_docker.return_value.containers.get.return_value = mock_container
        
        # We patch thrash_os_cache to avoid OOM in test
        with patch("sql_benchmarks.utils.system.thrash_os_cache") as mock_thrash:
            engine = ActianEngine(container_name="test_actian")
            
            # We need to mock _wait_for_ready to avoid the socket timeout
            with patch.object(ActianEngine, "_wait_for_ready") as mock_wait:
                engine.clear_cache()
                
                # Verify lifecycle
                mock_thrash.assert_called_once()
                # It should kill (remove force=True) and then run
                mock_docker.return_value.containers.get.assert_called_with("test_actian")
                mock_container.remove.assert_called_with(force=True)
                mock_docker.return_value.containers.run.assert_called()
