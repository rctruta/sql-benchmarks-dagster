import pytest
from dagster import MultiPartitionsDefinition
from unittest.mock import patch
import sql_benchmarks.partitions as p

def test_partition_generation_composite_logic():
    """
    Verify that N dimensions are encoded safely into 2 axes.
    """
    # 1. Mock the Context
    mock_ctx = {
        "engines": ["pg", "duck"],
        "dimensions": {
            "disk": ["ssd"],
            "rows": [100]
        }
    }
    
    # 2. Patch the module CTX
    with patch.object(p, 'CTX', mock_ctx):
        partitions_def, config_map = p.build_partitions()
        
        # 3. Verify Definition Type
        assert isinstance(partitions_def, MultiPartitionsDefinition)
        
        # 4. Verify Lookup Map Logic
        # The key should be: "disk_rows" (d) comes before "engine" (e) -> "ssd__100|pg"
        # We don't hardcode the sort order of axes in the assert, just that the map works.
        
        assert len(config_map) > 0
        
        # Grab a value and verify it decoded correctly
        # We expect 4 combinations: (ssd,100,pg), (ssd,100,duck)
        first_val = list(config_map.values())[0]
        assert first_val["engine"] in ["pg", "duck"]
        assert first_val["disk"] == "ssd"
        assert first_val["rows"] == 100

def test_definitions_load_correctly():
    from sql_benchmarks.definitions import defs
    assert len(defs.assets) > 0