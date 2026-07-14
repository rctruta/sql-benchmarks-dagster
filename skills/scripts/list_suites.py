#!/usr/bin/env python3
import httpx, json, os, sys, argparse
API = os.getenv("SB_API_BASE", "http://localhost:8000")
parser = argparse.ArgumentParser()
parser.add_argument("--category", required=True)
args = parser.parse_args()
print(json.dumps(httpx.get(f"{API}/v1/catalog/suites", params={"category": args.category}).json(), indent=2))
