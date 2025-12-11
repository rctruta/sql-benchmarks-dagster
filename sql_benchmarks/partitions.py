from dagster import StaticPartitionsDefinition
from .config_loader import ConfigLoader 

# Initialize the Configuration Compiler
try:
    COMPILER = ConfigLoader()
except ValueError as e:
    # If the compiler raises a structural error, we raise it here to fail hard at load time.
    raise e

# Extract the compiled artifacts for Dagster
partitions_def = StaticPartitionsDefinition(COMPILER.partition_keys)
SCENARIO_CONFIG = COMPILER.scenario_config

# If the config file was missing, we must ensure Dagster boots cleanly
if not COMPILER.partition_keys:
    partitions_def = StaticPartitionsDefinition(["init"])