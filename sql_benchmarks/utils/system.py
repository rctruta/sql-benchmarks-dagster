import os
import mmap
import platform
import sys
import psutil
import logging

# Use the dagster logger so these events show up in the UI
logger = logging.getLogger("dagster")


def capture_environment() -> dict:
    """
    Records the runtime CONDITIONS of an experiment for the result capsule.

    The Experiment ID fingerprints the question (config + SQL + code); this
    block records the lab bench it was answered on. Same ID on different
    hardware or engine versions = same question, distinct observation.
    """
    import duckdb
    import dagster

    env = {
        "python": platform.python_version(),
        "duckdb": duckdb.__version__,
        "dagster": dagster.__version__,
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "ram_total_gb": round(psutil.virtual_memory().total / (1024 ** 3), 1),
    }
    try:
        import polars
        env["polars"] = polars.__version__
    except ImportError:
        pass
    return env


def generator_id() -> str:
    """
    The capsule's maker's mark + the exact code revision that produced it —
    a SLSA-style 'builder' identity. Stamped into every capsule's metadata so
    each artifact says which tool, at which build, generated it.
    Falls back to the bare slug outside a git checkout.
    """
    import subprocess
    from ..constants import LAB_SLUG, ROOT_DIR
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT_DIR, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return f"{LAB_SLUG}@{sha}" if sha else LAB_SLUG
    except Exception:
        return LAB_SLUG

def thrash_os_cache(override_gb=None):
    """
    Forces OS Page Cache eviction by writing to a memory-mapped file 
    larger than available RAM.
    
    Args:
        override_gb (float): Optional. Force a specific flood size. 
                             If None, auto-detects Total RAM + 20%.
    """
    try:
        # 1. AUTO-DETECT RAM (Safety First)
        if os.getenv("SB_SILICON_SAFE") == "1":
            target_gb = 0.1 # Minimal thrash for flow verification
            log_msg = "SILICON SAFE MODE: Minimal Cache Thrash (100MB)"
        elif override_gb:
            target_gb = float(override_gb)
            log_msg = f"Manual Flood: {target_gb} GB"
        else:
            # We use 'available' memory to stay within system limits
            available_gb = psutil.virtual_memory().available / (1024 ** 3)
            # Cap at 50% of available OR 4GB, whichever is smaller
            target_gb = min(available_gb * 0.5, 4.0)
            log_msg = f"Auto-Flood: {target_gb:.2f} GB (Available: {available_gb:.2f} GB)"

        logger.info(log_msg)

        # 2. FAST FLOOD (MMAP)
        if target_gb <= 0: return # Skip if negative or zero

        size_bytes = int(target_gb * 1024 * 1024 * 1024)
        
        # Anonymous map (-1) and context manager to ensure it closes
        with mmap.mmap(-1, size_bytes) as mm:
            page_size = 4096            
            # Dirty the pages (Stride to be faster and less intensive)
            for i in range(0, size_bytes, page_size * 4):
                mm[i] = 1
            
        logger.info("OS Cache Thrashed.")
        
    except Exception as e:
        logger.warning(f"Cache thrash failed: {e}")