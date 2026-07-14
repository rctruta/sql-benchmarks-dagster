#!/usr/bin/env python3
import httpx, json, os, sys
API = os.getenv("SB_API_BASE", "http://localhost:8000")
print(json.dumps(httpx.get(f"{API}/v1/catalog/categories").json(), indent=2))
