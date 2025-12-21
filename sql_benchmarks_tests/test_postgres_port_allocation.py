
import pytest
from unittest.mock import MagicMock, patch
from sql_benchmarks.resources.postgres import PostgresEngine
from sqlalchemy.engine.url import make_url

@pytest.fixture
def mock_engine_deps():
    with patch("sql_benchmarks.resources.postgres.docker") as mock_docker, \
         patch("sql_benchmarks.resources.postgres.os") as mock_os:
        yield mock_docker, mock_os

def test_setup_docker_switches_port_if_busy(mock_engine_deps):
    mock_docker, mock_os = mock_engine_deps
    
    # 1. SETUP: Configured for 5432
    initial_url = "postgresql://user:pass@localhost:5432/db"
    engine = PostgresEngine(connection_string=initial_url)
    
    # 2. MOCK: Port 5432 is BUSY, 5433 is FREE
    # _check_port_available returns True if free (connect fails), False if busy (connect succeeds -> 0)
    # logic: return s.connect_ex(...) != 0
    # True = Free, False = Busy
    
    # We want setup_docker to retry 5 times (False) then fail loop.
    # Then _find_free_port is called.
    # We mocked _find_free_port to return 5433, checking calls.
    
    # Wait, does the test mock _find_free_port entirely?
    # Yes: patch.object(PostgresEngine, "_find_free_port", return_value=5433)
    # So we don't need to worry about calls INSIDE _find_free_port.
    # We just need setup_docker's loop to fail.
    
    mock_responses = [False] * 6 # 5 retries + extra buffer
    
    with patch.object(PostgresEngine, "_check_port_available", side_effect=mock_responses) as mock_check, \
         patch.object(PostgresEngine, "_find_free_port", return_value=5433) as mock_find:
        
        # 3. ACT
        # Mock other calls
        with patch.object(PostgresEngine, "_kill_zombie_container"):
             engine.setup_docker()

        # 4. ASSERT
        # Ensure it tried to find a new port
        mock_find.assert_called_once()
        
        # Ensure connection string was updated (via runtime check)
        # connection_string is immutable, so we check what get_engine returns
        # OR check the private attr directly if needed for unit testing
        assert engine._runtime_connection_string is not None
        final_url = make_url(engine._runtime_connection_string)
        assert final_url.port == 5433
        
        # Ensure Docker run was called with new port
        mock_client = mock_docker.from_env.return_value
        call_kwargs = mock_client.containers.run.call_args[1]
        assert call_kwargs['ports'] == {'5432/tcp': 5433}

def test_setup_docker_uses_configured_port_if_free(mock_engine_deps):
    mock_docker, mock_os = mock_engine_deps
    
    # 1. SETUP
    initial_url = "postgresql://user:pass@localhost:5432/db"
    engine = PostgresEngine(connection_string=initial_url)
    
    # 2. MOCK: 5432 is FREE
    with patch.object(PostgresEngine, "_check_port_available", return_value=True) as mock_check:
         
         with patch.object(PostgresEngine, "_kill_zombie_container"):
             engine.setup_docker()

         # 3. ASSERT
         final_url = make_url(engine.connection_string)
         assert final_url.port == 5432
         
         mock_client = mock_docker.from_env.return_value
         call_kwargs = mock_client.containers.run.call_args[1]
         assert call_kwargs['ports'] == {'5432/tcp': 5432}
