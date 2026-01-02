import pytest
import os
import yaml
from pathlib import Path
from sql_benchmarks.config_loader import ConfigLoader

# Define the root of the test fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"

# --- UTILITY FIXTURE (Loads files from the static directory) ---

@pytest.fixture
def load_config_from_fixture(tmpdir):
    """
    Returns a callable function that copies a static fixture file
    to the temporary directory, allowing ConfigLoader to run against it.
    """
    def _yaml_factory(fixture_filename):
        # 1. Define source and destination paths
        source_path = FIXTURES_DIR / fixture_filename
        temp_dir = Path(tmpdir)
        temp_file = temp_dir / "active.yaml"
        
        # 2. Copy the content to the mocked execution path
        with open(source_path, 'r') as src, open(temp_file, 'w') as dst:
            dst.write(src.read())

        # 3. Return the temporary path
        return str(temp_file)
    
    return _yaml_factory

# --- TEST CASES ---

# The test now requests the 'load_config_from_fixture' factory.
def test_config_success(load_config_from_fixture):
    """Tests the happy path: alias resolution and key generation."""
    
    # 1. Load the good config file into the temporary directory
    config_path = load_config_from_fixture("good_config.yaml")
    
    # 2. Instantiate the ConfigLoader using the temporary path
    class TestConfigLoader(ConfigLoader):
        def __init__(self):
            super().__init__(config_path=config_path)

    compiler = TestConfigLoader()

    # 3. Verify Partitions (Symbolic combination)
    expected_keys = [
        'ssd_small', 'hdd_small', 
        'ssd_medium', 'hdd_medium'
    ]
    assert sorted(compiler.partition_keys) == sorted(expected_keys)

    # 4. Verify SCENARIO_CONFIG (Numeric/Literal payload)
    assert compiler.scenario_config['ssd_small']['rows'] == 100000
    assert compiler.scenario_config['hdd_medium']['rows'] == 1000000


def test_config_fail_alias(load_config_from_fixture):
    """Tests the architectural rule: strict validation of aliases."""
    
    config_path = load_config_from_fixture("bad_alias_config.yaml")
    
    class TestConfigLoader(ConfigLoader):
        def __init__(self):
            super().__init__(config_path=config_path)

    with pytest.raises(ValueError) as excinfo:
        TestConfigLoader()

    # Verify the exact error message that enforces the contract
    assert "STRICT VIOLATION" in str(excinfo.value) or "SCHEMA ERROR" in str(excinfo.value)


def test_config_fail_matrix(load_config_from_fixture):
    """Tests the structural rule: matrix block must exist."""
    
    config_path = load_config_from_fixture("bad_structure_config.yaml")
    
    class TestConfigLoader(ConfigLoader):
        def __init__(self):
            super().__init__(config_path=config_path)

    # Now this can fail either in compile (KeyError) OR in validation (SCHEMA ERROR)
    with pytest.raises((ValueError, KeyError)) as excinfo:
        TestConfigLoader()
        
    # Verify the exact error message that enforces the contract
    assert "CRITICAL: Experiment must define a 'matrix'" in str(excinfo.value)