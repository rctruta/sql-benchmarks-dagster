import yaml
from sql_benchmarks.utils.common import generate_partition_keys
import sys
import os

path = "sql_benchmarks/experiments/queue/smoke_v8.yaml"
with open(path, "r") as f:
    config = yaml.safe_load(f)

matrix = config.get("execution", {}).get("matrix")
print(f"Matrix: {matrix}")
keys = generate_partition_keys(matrix)
print(f"Keys: {keys}")
