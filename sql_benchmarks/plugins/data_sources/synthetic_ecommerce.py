import pandas as pd
import numpy as np
import os
from dagster import MaterializeResult, MetadataValue

# This function is the CONTRACT. The factory calls this.
def generate(context, params, table_name, output_dir):
    
    # Dispatcher: Decide which logic to run based on table name
    if table_name == "customers":
        return _gen_customers(context, params, output_dir)
    elif table_name == "orders":
        return _gen_orders(context, params, output_dir)
    else:
        raise ValueError(f"Unknown table: {table_name}")

def _gen_customers(context, params, output_dir):
    key = context.partition_key
    num_rows = params['rows']
    
    context.log.info(f"Generating {num_rows} customers...")
    
    df = pd.DataFrame({
        "customer_id": np.arange(1, num_rows + 1),
        "name": [f"Customer_{i}" for i in range(1, num_rows + 1)],
        "region": np.random.choice(['NA', 'EU', 'APAC', 'LATAM'], size=num_rows)
    })
    
    # Save using the unique key
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"customers_{key}.parquet")
    df.to_parquet(output_path, index=False)
    
    return MaterializeResult(
        metadata={
            "path": MetadataValue.path(output_path),
            "customer_count": MetadataValue.int(num_rows),
            "experiment_config": MetadataValue.json(params)
        }
    )

def _gen_orders(context, params, output_dir):
    key = context.partition_key
    num_rows = params['rows']
    orphan_pct = params['orphan_rate']
    ratio = params['ratio']
    
    max_valid_id = max(int(num_rows / ratio), 1)
    num_orphans = int(num_rows * orphan_pct)
    num_valid = num_rows - num_orphans
    
    context.log.info(f"Generating orders with {orphan_pct:.0%} orphans...")

    np.random.seed(42)
    valid_ids = np.random.randint(1, max_valid_id + 1, size=num_valid)
    
    orphan_start = max_valid_id + 2
    orphan_end = orphan_start + (max_valid_id * 2) 
    orphan_ids = np.random.randint(orphan_start, orphan_end, size=num_orphans)
    
    all_ids = np.concatenate([valid_ids, orphan_ids])
    np.random.shuffle(all_ids)
    
    df = pd.DataFrame({
        "order_id": np.arange(1, num_rows + 1),
        "customer_id": all_ids,
        "amount": np.random.uniform(10.0, 500.0, size=num_rows).round(2),
        "created_at": pd.date_range(start="2024-01-01", periods=num_rows, freq="s"),
    })

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"orders_{key}.parquet")
    df.to_parquet(output_path, index=False)
    
    return MaterializeResult(
        metadata={
            "path": MetadataValue.path(output_path),
            "row_count": MetadataValue.int(num_rows),
            "orphan_percentage": MetadataValue.float(orphan_pct),
            "experiment_config": MetadataValue.json(params)
        }
    )