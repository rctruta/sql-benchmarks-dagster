import os
import pandas as pd
import numpy as np
from dagster import asset, AssetExecutionContext
from ..partitions import size_partitions, ROW_COUNTS

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "staging")

# Config: 10% of customers in the orders table will not exist in the customers table
ORPHAN_PERCENTAGE = 0.10 

@asset(
    partitions_def=size_partitions,
    group_name="data_generation",
    description="The Parent Table. Contains valid Customer IDs."
)
def customers_parquet(context: AssetExecutionContext) -> str:
    partition_key = context.partition_key
    # Let's say we have 1 customer for every 10 orders on average
    num_customers = max(ROW_COUNTS[partition_key] // 10, 1000)
    
    context.log.info(f"Generating {num_customers} customers for partition {partition_key}")
    
    # Generate simple sequential IDs for the parent table
    df = pd.DataFrame({
        "customer_id": np.arange(1, num_customers + 1),
        "name": [f"Customer_{i}" for i in range(1, num_customers + 1)],
        "region": np.random.choice(['NA', 'EU', 'APAC', 'LATAM'], size=num_customers)
    })
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"customers_{partition_key}.parquet")
    df.to_parquet(output_path, index=False)
    
    # Store the count as metadata so downstream assets know the range
    context.add_output_metadata({"customer_count": num_customers})
    return output_path

@asset(
    partitions_def=size_partitions,
    group_name="data_generation",
    deps=["customers_parquet"], # Explicit dependency
    description="The Child Table. Contains Orders, some of which are orphans."
)
def orders_parquet(context: AssetExecutionContext) -> str:
    partition_key = context.partition_key
    num_orders = ROW_COUNTS[partition_key]
    
    # We need to know the max ID from the parent table to generate valid/invalid links.
    # Logic: 10 orders per customer avg.
    max_valid_id = max(ROW_COUNTS[partition_key] // 10, 1000)

    # 1. Calculate Orphans
    num_orphans = int(num_orders * ORPHAN_PERCENTAGE)
    num_valid = num_orders - num_orphans
    
    context.log.info(f"Generating {num_valid} valid orders and {num_orphans} ORPHANS.")

    np.random.seed(42)

    # 2. Generate IDs
    # Valid: IDs that definitely exist in customers_parquet (1 to max_valid_id)
    valid_ids = np.random.randint(1, max_valid_id + 1, size=num_valid)
    
    # Orphans: IDs that definitely DO NOT exist (max_valid_id + 1000 and up)
    orphan_ids = np.random.randint(max_valid_id + 1000, max_valid_id + 5000, size=num_orphans)
    
    # Combine and Shuffle
    all_ids = np.concatenate([valid_ids, orphan_ids])
    np.random.shuffle(all_ids)

    df = pd.DataFrame({
        "order_id": np.arange(1, num_orders + 1),
        "customer_id": all_ids,
        "amount": np.random.uniform(10.0, 500.0, size=num_orders).round(2),
        "created_at": pd.date_range(start="2024-01-01", periods=num_orders, freq="s"),
    })

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"orders_{partition_key}.parquet")
    df.to_parquet(output_path, index=False)
    
    return output_path