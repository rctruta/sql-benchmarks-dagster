#!/usr/bin/env python3
import httpx, json, os, sys, argparse
API = os.getenv("SB_API_BASE", "http://localhost:8000")
parser = argparse.ArgumentParser()
parser.add_argument("--yaml-file", required=True)
args = parser.parse_args()
with open(args.yaml_file) as f:
    yaml_content = f.read()
print(json.dumps(httpx.post(f"{API}/v1/experiments", json={"config_yaml": yaml_content}, timeout=30).json(), indent=2))
