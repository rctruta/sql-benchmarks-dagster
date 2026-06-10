"""
SQL Benchmarks REST API server.

Usage:
    python serve.py

Environment variables:
    SB_API_HOST     Bind host (default: 0.0.0.0)
    SB_API_PORT     Bind port (default: 8000)
    SB_API_RELOAD   Enable hot reload for development (default: false)
"""
import os

import uvicorn

from sql_benchmarks.api.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "serve:app",
        host=os.getenv("SB_API_HOST", "0.0.0.0"),
        port=int(os.getenv("SB_API_PORT", "8000")),
        reload=os.getenv("SB_API_RELOAD", "false").lower() == "true",
        log_level="info",
    )
