import pytest
from unittest.mock import MagicMock
from sql_benchmarks.assets.reporting import parse_events_to_records

# --- MOCK HELPER ---
class MockMetadataValue:
    def __init__(self, value):
        self.value = value

def create_mock_event(asset_name, metadata_dict):
    """Creates a fake Dagster Event structure for testing."""
    mock_event = MagicMock()
    mock_event.asset_key.path = [asset_name]
    
    # Structure: event.event_log_entry.dagster_event.step_materialization_data.materialization.metadata
    mat = mock_event.event_log_entry.dagster_event.step_materialization_data.materialization
    
    # Convert dict to MockMetadataValues
    mat.metadata = {k: MockMetadataValue(v) for k, v in metadata_dict.items()}
    
    return mock_event

# --- TESTS ---

def test_reporting_filters_by_experiment_id():
    """Verify we ignore stale records from old experiments."""
    current_id = "exp_v7"
    
    events = [
        # Good Record
        create_mock_event("bench_1", {
            "experiment_id": "exp_v7",
            "duration_seconds": 1.5,
            "config_engine": "postgres"
        }),
        # Stale Record (Old ID)
        create_mock_event("bench_1", {
            "experiment_id": "exp_v1_old", # mismatch
            "duration_seconds": 99.9,
            "config_engine": "postgres"
        })
    ]
    
    records = parse_events_to_records(events, current_id)
    
    assert len(records) == 1
    assert records[0]["Duration"] == 1.5

def test_reporting_extracts_dynamic_dimensions():
    """Verify we correctly pull dim_rows and derived_selectivity."""
    events = [
        create_mock_event("bench_ssd", {
            "experiment_id": "current",
            "duration_seconds": 2.0,
            "config_engine": "duckdb",
            "dim_rows": 100_000,
            "derived_selectivity": 0.01,
            "dim_disk_type": "ssd" # Optional dimension
        })
    ]
    
    records = parse_events_to_records(events, "current")
    row = records[0]
    
    assert row["Rows"] == 100_000
    assert row["Selectivity"] == 0.01
    assert row["System"] == "duckdb (ssd)" # Verifies dynamic label creation