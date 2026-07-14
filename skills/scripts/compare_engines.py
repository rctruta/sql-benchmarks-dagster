#!/usr/bin/env python3
import httpx, json, os, sys, argparse
API = os.getenv("SB_API_BASE", "http://localhost:8000")
parser = argparse.ArgumentParser()
parser.add_argument("exp_id")
parser.add_argument("--partition", default=None)
args = parser.parse_args()
params = {"partition": args.partition} if args.partition else {}
print(json.dumps(httpx.get(f"{API}/v1/results/{args.exp_id}/compare", params=params).json(), indent=2))
