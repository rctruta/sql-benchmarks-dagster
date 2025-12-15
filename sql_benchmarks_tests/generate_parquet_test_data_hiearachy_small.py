import polars as pl
import os
import numpy as np # Used for defining NULL/None values

# --- Define the static file path ---
BASE_PATH = os.path.join("sql_benchmarks_tests", "fixtures")
FILE_PATH = os.path.join(BASE_PATH, "test_hierarchy_small.parquet")

# 1. Ensure the directory exists
os.makedirs(BASE_PATH, exist_ok=True)

# 2. Define the data structure
data = {
    "id": [1, 2, 3, 4, 5, 6],
    # Use None for the root nodes (Polars will handle the null conversion)
    "parent_id": [None, 1, 1, 2, 4, None], 
    "name": ["Root", "Child_A", "Child_B", "Grandchild_A", "Great_Grandchild", "Separate_Root"]
}

# 3. Create the Polars DataFrame with explicit type setting
df = pl.DataFrame(data).with_columns(
    pl.col("id").cast(pl.Int64),
    pl.col("parent_id").cast(pl.Int64) # This will store None as null
)

# 4. Write to Parquet
df.write_parquet(FILE_PATH)

print(f"✅ Static Parquet file created at: {FILE_PATH}")