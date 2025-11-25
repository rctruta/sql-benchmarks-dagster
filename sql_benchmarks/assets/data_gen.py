import os
import pandas as pd
import numpy as np
from dagster import asset, AssetExecutionContext
from ..partitions import size_partitions, ROW_COUNTS

# NEW: We calculate the absolute path to a "data" folder in your project root.
# This ensures the file always goes to the same place, even if you move the script.
# We go up 3 levels: assets -> sql_benchmarks -> sql_benchmarks (package) -> ROOT
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "staging")

@asset(
    partitions_def=size_partitions,
    group_name="data_generation",
    description="Generates a synthetic dataset of e-commerce orders. Size depends on the partition selected."
)
def synthetic_orders_parquet(context: AssetExecutionContext) -> str:
    """
    Generates synthetic data and saves it to a parquet file.
    
    Returns:
        str: The file path to the generated parquet file.
    """
    # 1. Resolve the partition key (e.g., 'small', 'medium') to a concrete row count.
    # This allows us to decouple the 'what' (partition name) from the 'how much' (row count).
    partition_key = context.partition_key
    num_rows = ROW_COUNTS[partition_key]

    context.log.info(f"Generating {num_rows} rows for partition: {partition_key}")

    # 2. Generate synthetic data using NumPy for performance.
    # We use a fixed seed to ensure benchmarks are reproducible across runs.
    np.random.seed(42)
    
    data = {
        "order_id": np.arange(num_rows),
        "customer_id": np.random.randint(1, num_rows // 10, size=num_rows),  # 10 orders per customer avg
        "amount": np.random.uniform(10.0, 500.0, size=num_rows).round(2),
        "status": np.random.choice(['PENDING', 'SHIPPED', 'DELIVERED', 'RETURNED'], size=num_rows),
        "created_at": pd.date_range(start="2024-01-01", periods=num_rows, freq="s"), # 1 sec intervals
    }

    df = pd.DataFrame(data)

    # 3. Ensure the output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 4. Write to Parquet (partitioned by filename)
    # Naming convention: orders_small.parquet, orders_medium.parquet
    output_path = os.path.join(OUTPUT_DIR, f"orders_{partition_key}.parquet")
    df.to_parquet(output_path, index=False)

    context.log.info(f"Successfully saved dataset to {output_path}")

    # Return the path so downstream assets know where to look
    return output_path