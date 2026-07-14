#!/usr/bin/env python3
import httpx, json, os, sys
API = os.getenv("SB_API_BASE", "http://localhost:8000")
if len(sys.argv) < 2:
    print("Usage: get_means_by_partition.py <exp_id>")
    sys.exit(1)
print(json.dumps(httpx.get(f"{API}/v1/results/{sys.argv[1]}/projections/means").json(), indent=2))
