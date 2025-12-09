import pytest
from dagster import materialize_to_memory

# Standard imports work now because conftest.py ran first
from sql_benchmarks.assets.data_factory import data_assets
from sql_benchmarks.assets.ingestion_factory import ingestion_assets
from sql_benchmarks.assets.benchmark_factory import benchmark_assets
from sql_benchmarks.partitions import partitions_def

def get_asset_key(asset_def):
    return next(iter(asset_def.keys))

# ==========================================
# 1. DATA FACTORY
# ==========================================
def test_data_factory_metadata():
    if not data_assets: pytest.skip("No data assets generated")
    
    asset = data_assets[0]
    key = get_asset_key(asset)
    
    # Correct Name from your logs
    assert asset.group_names_by_key[key] == "data_generation"
    assert "parquet" in key.path[-1]

def test_smoke_run_data_generation():
    if not data_assets: pytest.skip("No data assets")
    target_asset = data_assets[0]
    
    # Get valid keys from the definition
    valid_keys = partitions_def.get_partition_keys()
    if not valid_keys: pytest.skip("No partitions defined")
    
    result = materialize_to_memory(
        [target_asset],
        partition_key=valid_keys[0]
    )
    assert result.success

# ==========================================
# 2. INGESTION FACTORY
# ==========================================
def test_ingestion_factory_structure():
    if not ingestion_assets: pytest.skip("No ingestion assets")
    
    pg_assets = [a for a in ingestion_assets if "pg_" in get_asset_key(a).path[-1]]
    
    if pg_assets:
        pg = pg_assets[0]
        key = get_asset_key(pg)

        assert pg.group_names_by_key[key] == "ingest_postgres"

# ==========================================
# 3. BENCHMARK FACTORY
# ==========================================
def test_benchmark_factory_produces_assets():
    if not benchmark_assets: return 

    bench = benchmark_assets[0]
    key = get_asset_key(bench)
    group = bench.group_names_by_key[key]
    
    # Correct Names from your logs
    assert group in ["bench_postgres", "bench_duckdb"]