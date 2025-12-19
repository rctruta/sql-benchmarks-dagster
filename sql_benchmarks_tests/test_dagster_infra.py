import pytest
from dagster import StaticPartitionsDefinition
from sql_benchmarks.partitions import partitions_def, SCENARIO_CONFIG

def test_partitions_configuration():
    """
    Verifies that the partitions module correctly initialized a StaticPartitionsDefinition
    and a corresponding scenario config map.
    """
    # 1. Verify Definition Type (We moved from Multi -> Static)
    assert isinstance(partitions_def, StaticPartitionsDefinition)
    
    # 2. Verify Config Integrity
    # Logic: Every partition key must have a corresponding entry in SCENARIO_CONFIG
    keys = partitions_def.get_partition_keys()
    
    # If we are in "init" mode (no config found), strict checks might differ,
    # but for a valid test env we expect keys.
    if keys != ["init"]:
        for k in keys:
            assert k in SCENARIO_CONFIG
            assert isinstance(SCENARIO_CONFIG[k], dict)

def test_definitions_load_correctly():
    """
    High-level smoke test to ensure the entire Dagster repository can load.
    This implicitly checks all imports in definitions.py, assets, resources, etc.
    """
    from sql_benchmarks.definitions import defs
    assert len(defs.assets) > 0
    assert defs.resources is not None