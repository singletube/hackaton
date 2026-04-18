import asyncio
import os
import sys
import logging

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from core.database import StateDB
from core.provider.yandex import YandexDiskProvider
from core.manager import HybridManager

logging.basicConfig(level=logging.INFO)

async def main():
    TOKEN = "y0__xCzmrXmCBjOv0Ag0o_Vjhdt6Z44hHi-AWWAayZ3qZpaNNl-jw"
    TEST_DIR_NAME = "/CloudBridge_LocalTest"
    
    db = StateDB("test_sync.db")
    await db.initialize()
    
    provider = YandexDiskProvider(TOKEN)
    manager = HybridManager(db, provider, "cache_sync_test")
    
    try:
        print(f"--- Creating Remote Directory: {TEST_DIR_NAME} ---")
        success = await provider.create_directory(TEST_DIR_NAME)
        if success:
            print("Successfully created (or already exists).")
        
        print("--- Syncing Root Directory ---")
        await manager.sync_directory("/")
        
        print("--- Verifying in Database ---")
        item = await db.get_item(TEST_DIR_NAME)
        if item:
            print(f"SUCCESS: Folder found in DB!")
            print(f"Details: {item}")
        else:
            print("FAILURE: Folder NOT found in DB after sync.")
            
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        await provider.close()

if __name__ == "__main__":
    asyncio.run(main())
