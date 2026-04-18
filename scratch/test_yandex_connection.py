import asyncio
import os
import sys

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import logging
from core.database import StateDB
from core.provider.yandex import YandexDiskProvider
from core.manager import HybridManager

logging.basicConfig(level=logging.INFO)

async def main():
    TOKEN = "y0__xCzmrXmCBjOv0Ag0o_Vjhdt6Z44hHi-AWWAayZ3qZpaNNl-jw"
    DB_PATH = "yandex_test.db"
    CACHE_DIR = "cache_test"
    
    print(f"Connecting to Yandex.Disk with token: {TOKEN[:4]}...{TOKEN[-4:]}")
    
    db = StateDB(DB_PATH)
    await db.initialize()
    
    provider = YandexDiskProvider(TOKEN)
    manager = HybridManager(db, provider, CACHE_DIR)
    
    try:
        print("--- Syncing Root Directory ---")
        await manager.sync_directory("/")
        
        print("--- Root Directory Contents (from DB) ---")
        children = await manager.get_children("/")
        if not children:
            print("No items found.")
        else:
            for child in children:
                print(f"[{child['type']}] {child['name']} (Size: {child['size']} bytes) - Status: {child['status']}")
                
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        await provider.close()

if __name__ == "__main__":
    asyncio.run(main())
