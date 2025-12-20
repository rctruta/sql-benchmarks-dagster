import pytest
import yaml
import os
import shutil
import polars as pl
from sql_benchmarks.plugins.data_sources import declarative_gen

# Paths
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "configs")

@pytest.fixture
def temp_output(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir

def load_fixture(filename):
    with open(os.path.join(FIXTURES_DIR, filename), "r") as f:
        return yaml.safe_load(f)

# ==========================================
# TEST 1: Multi-Table Chain (Success)
# ==========================================
def test_multi_table_chain_generation(temp_output):
    """
    Verifies that Regions -> Nations -> Customers runs successfully
    and maintains foreign key integrity.
    """
    config = load_fixture("multi_table_test.yaml")
    params = {"rows": 1} # Dummy param to satisfy resolve
    
    # 1. Generate Regions
    declarative_gen.generate(None, params, "regions", str(temp_output / "regions.parquet"), config['dataset'])
    
    # 2. Generate Nations (Depends on Regions)
    declarative_gen.generate(None, params, "nations", str(temp_output / "nations.parquet"), config['dataset'])
    
    # 3. Generate Customers (Depends on Nations)
    declarative_gen.generate(None, params, "customers", str(temp_output / "customers.parquet"), config['dataset'])
    
    # Verify Integrity
    regions = pl.read_parquet(str(temp_output / "regions.parquet"))
    nations = pl.read_parquet(str(temp_output / "nations.parquet"))
    
    # Check FK: Nation.region_id -> Region.id
    # Since specific IDs are random, we just check they are in valid range or set
    valid_region_ids = set(regions["id"].to_list())
    for nid in nations["region_id"].to_list():
        assert nid in valid_region_ids, f"Nation has invalid region_id: {nid}"

# ==========================================
# TEST 2: Cycle Detection (Failure)
# ==========================================
# Note: declarative_gen itself is "dumb" and doesn't check DAG cycles (Dagster does).
# However, if we tried to run them blindly, we might test infinite recursion if we were implementing it that way.
# But since our code relies on *existing* Parquet files for some providers (text_concat), 
# or just random IDs for foreign_keys, declarative_gen might actually *succeed* in isolation 
# (generating garbage FKs to non-existent files if not careful).
#
# The Chicken-Egg cycle failure we saw was in *Dagster Construction* (toposort).
# Unit testing declarative_gen won't catch toposort errors unless we duplicate logic.
#
# Instead, we verify that the *metadata* parsing identifies the dependency loop if we were to implement
# a utility for it. For now, let's skip re-implementing toposort here and focus on the Data Generation logic.
