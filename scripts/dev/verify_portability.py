#!/usr/bin/env python3
import os
import sys
import subprocess
import importlib
from datetime import datetime

def check_python_version():
    print("[1/5] Checking Python Version...")
    major, minor = sys.version_info[:2]
    if major == 3 and minor >= 10:
        print(f"      Python {major}.{minor} detected.")
        return True
    else:
        print(f"      ERROR: Python 3.10+ required (Detected {major}.{minor})")
        return False

def check_dependencies():
    print("[2/5] Checking Dependencies...")
    required = ["dagster", "polars", "duckdb", "docker", "psutil", "yaml"]
    missing = []
    for lib in required:
        try:
            importlib.import_module(lib if lib != "yaml" else "yaml")
            print(f"      {lib} is installed.")
        except ImportError:
            missing.append(lib)
    
    if missing:
        print(f"      MISSING: {', '.join(missing)}")
        return False
    return True

def check_docker():
    print("[3/5] Checking Docker Daemon...")
    try:
        import docker
        client = docker.from_env()
        client.ping()
        print("      Docker daemon is reachable.")
        return True
    except Exception as e:
        print(f"      ERROR: Docker daemon not running or unreachable: {e}")
        return False

def check_filesystem():
    print("[4/5] Checking Filesystem...")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    required_dirs = ["data", "sql_benchmarks/experiments/queue", "dagster_home"]
    
    for d in required_dirs:
        path = os.path.join(root, d)
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
                print(f"      Created {d}/")
            except Exception as e:
                print(f"      FAILED to create {d}/: {e}")
                return False
        else:
            if os.access(path, os.W_OK):
                print(f"      {d}/ is writable.")
            else:
                print(f"      {d}/ is NOT writable.")
                return False
    return True

def check_dagster_definitions():
    print("[5/5] Checking Dagster Definition Integrity...")
    try:
        # Set environment so definitions load correctly
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        os.environ["DAGSTER_HOME"] = os.path.join(root, "dagster_home")
        
        # Import definitions to see if assets/factories fail to initialize
        sys.path.append(root)
        from sql_benchmarks.definitions import defs
        print("      Dagster definitions loaded successfully.")
        return True
    except Exception as e:
        print(f"      ERROR: Definitions failed to load: {e}")
        return False

def run_all():
    print(f"--- SQL Benchmarks Portability Audit ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ---")
    results = [
        check_python_version(),
        check_dependencies(),
        check_docker(),
        check_filesystem(),
        check_dagster_definitions()
    ]
    
    print("-" * 60)
    if all(results):
        print("SUCCESS: Environment is ready for benchmarking.")
        sys.exit(0)
    else:
        print("FAILURE: Please fix the issues above before running.")
        sys.exit(1)

if __name__ == "__main__":
    run_all()
