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
            # psutil returns bytes, convert to GB
            total_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
            # Safety Factor: 1.2x RAM ensures we push out cached pages
            target_gb = total_ram_gb * 0.75
            log_msg = f"🌊 Auto-Flood: {target_gb:.2f} GB (120% of RAM)"

        logger.info(log_msg)

        # 2. FAST FLOOD (MMAP)
        # We don't allocate a slow bytearray. We ask the OS for pages.
        size_bytes = int(target_gb * 1024 * 1024 * 1024)
        
        # Anonymous map (not backed by file on disk, purely RAM/Swap)
        # -1 indicates anonymous mapping
        # We use a context manager to ensure it closes
        with mmap.mmap(-1, size_bytes) as mm:
            # Touch every 4KB page to force physical allocation
            # This is the "Speed Hack" - we don't write every byte, just the headers
            page_size = 4096
            
            # Dirty the pages
            for i in range(0, size_bytes, page_size):
                mm[i] = 1
            
        logger.info("✅ OS Cache Thrashed.")
        
    except Exception as e:
        logger.warning(f"❌ Cache thrash failed: {e}")