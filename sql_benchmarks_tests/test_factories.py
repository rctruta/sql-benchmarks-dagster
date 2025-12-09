import pytest
from dagster import materialize_to_memory

# We import the asset lists directly
# Note: Ensure you have a valid active.yaml or this import might fail.
from sql_benchmarks.assets.data_factory import data_assets
from sql_benchmarks.assets.ingestion_factory import ingestion_assets

def test_data_factory_produces_assets():
    """Verify data assets are created for tables in config"""
    # Assuming active.yaml has 'customers' and 'orders'
    asset_names = [a.key.path[-1] for a in data_assets]
    
    # We check if *some* expected assets exist. 
    # Adjust 'customers_parquet' based on your actual active.yaml
    assert any("parquet" in name for name in asset_names)

def test_ingestion_factory_produces_assets():
    """Verify ingestion assets exist for both engines"""
    asset_names = [a.key.path[-1] for a in ingestion_assets]
    
    # Should have Postgres and DuckDB assets
    assert any("pg_" in name for name in asset_names)
    assert any("duckdb_" in name for name in asset_names)

def test_smoke_run_data_generation():
    """
    CRITICAL: Actually run the code in-memory for a tiny partition.
    This proves the whole chain (Factory -> Plugin -> Polars) works.
    """
    # Pick one asset to test
    if not data_assets:
        pytest.skip("No data assets found config")
        
    target_asset = data_assets[0]
    
    # Run it!
    result = materialize_to_memory(
        [target_asset],
        partition_key="small_ssd" # Ensure 'small' exists in your dimensions
    )
    
    assert result.success
    assert result.output_for_node(target_asset.key.path[-1])