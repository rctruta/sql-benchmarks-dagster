import mmap
import psutil
import logging

# Use the dagster logger so these events show up in the UI
logger = logging.getLogger("dagster")

def thrash_os_cache(override_gb=None):
    """
    Forces OS Page Cache eviction by writing to a memory-mapped file 
    larger than available RAM.
    
    Args:
        override_gb (float): Optional. Force a specific flood size. 
                             If None, auto-detects Total RAM + 20%.
    """
    try:
        # 1. AUTO-DETECT RAM
        if override_gb:
            target_gb = float(override_gb)
            log_msg = f"🌊 Manual Flood: {target_gb} GB"
        else:
            total_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
            target_gb = total_ram_gb * 0.75
            log_msg = f"🌊 Auto-Flood: {target_gb:.2f} GB (75% of RAM)"

        logger.info(log_msg)

        # 2. FAST FLOOD (MMAP)
        size_bytes = int(target_gb * 1024 * 1024 * 1024)
        
        # Anonymous map (-1) and context manager to ensure it closes
        with mmap.mmap(-1, size_bytes) as mm:
            page_size = 4096            
            # Dirty the pages
            for i in range(0, size_bytes, page_size):
                mm[i] = 1
            
        logger.info("✅ OS Cache Thrashed.")
        
    except Exception as e:
        logger.warning(f"❌ Cache thrash failed: {e}")