import os
import pandas as pd
import numpy as np
from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue
from ..partitions import partitions_def, SCENARIO_CONFIG

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "staging")

@asset(
    partitions_def=partitions_def,
    group_name="data_generation",
    deps=["customers_parquet"], 
    description="**Child Table.** Generates Orders linking to Customers with configurable Orphans."
)
def orders_parquet(context: AssetExecutionContext) -> MaterializeResult:
    # 1. GET CONFIG
    key = context.partition_key
    params = SCENARIO_CONFIG[key]
    
    num_rows = params['rows']
    orphan_pct = params['orphan_rate']
    ratio = params['ratio']
    
    # 2. LOGIC
    # Ensure we have at least 1 customer to avoid errors
    max_valid_id = max(int(num_rows / ratio), 1)

    # Calculate counts
    num_orphans = int(num_rows * orphan_pct)
    num_valid = num_rows - num_orphans
    
    context.log.info(f"Generating {num_valid} valid + {num_orphans} orphans. Max Customer ID: {max_valid_id}")

    np.random.seed(42)

    # Generate IDs
    valid_ids = np.random.randint(1, max_valid_id + 1, size=num_valid)
    
    # Orphan Logic (Start after the max_valid_id)
    orphan_start = max_valid_id + 2
    orphan_end = orphan_start + (max_valid_id * 2) 
    orphan_ids = np.random.randint(orphan_start, orphan_end, size=num_orphans)
    
    # Combine
    all_ids = np.concatenate([valid_ids, orphan_ids])
    np.random.shuffle(all_ids)
    
    df = pd.DataFrame({
        "order_id": np.arange(1, num_rows + 1),
        "customer_id": all_ids,
        "amount": np.random.uniform(10.0, 500.0, size=num_rows).round(2),
        "created_at": pd.date_range(start="2024-01-01", periods=num_rows, freq="s"),
    })

    # 3. SAVE (CRITICAL FIX HERE)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    # Changed {partition} to {key} so 'small_clean' and 'small_skew10' don't overwrite each other!
    output_path = os.path.join(OUTPUT_DIR, f"orders_{key}.parquet")
    df.to_parquet(output_path, index=False)
    
    # 4. RETURN MATERIALIZE RESULT
    # This replaces the simple "return output_path"
    return MaterializeResult(
        metadata={
            "path": MetadataValue.path(output_path),
            "row_count": MetadataValue.int(num_rows),
            "orphan_percentage": MetadataValue.float(orphan_pct),
            # The Metatrace: Full config dump
            "experiment_config": MetadataValue.json(params)
        }
    )

@asset(
    partitions_def=partitions_def,
    group_name="data_generation",
    description="**Parent Table.** Generates a list of valid Customers."
)
def customers_parquet(context: AssetExecutionContext) -> MaterializeResult:
    key = context.partition_key
    params = SCENARIO_CONFIG[key]
    
    num_rows = params['rows']
    # Note: We generate 'num_rows' customers. 
    # Since orders uses num_rows/ratio (e.g. 100k/10 = 10k), 
    # we have plenty of valid customers (100k) to satisfy the orders (need 10k).
    
    context.log.info(f"Generating {num_rows} customers for partition {key}")
    
    df = pd.DataFrame({
        "customer_id": np.arange(1, num_rows + 1),
        "name": [f"Customer_{i}" for i in range(1, num_rows + 1)],
        "region": np.random.choice(['NA', 'EU', 'APAC', 'LATAM'], size=num_rows)
    })
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    # Changed {partition} to {key}
    output_path = os.path.join(OUTPUT_DIR, f"customers_{key}.parquet")
    df.to_parquet(output_path, index=False)
    
    return MaterializeResult(
        metadata={
            "path": MetadataValue.path(output_path),
            "customer_count": MetadataValue.int(num_rows),
            "experiment_config": MetadataValue.json(params)
        }
    )