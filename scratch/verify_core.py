import asyncio
import os
import sys
from datetime import datetime

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from core.models import ItemType, FileStatus, CloudItem
from core.database import StateDB
from core.provider.yandex import YandexDiskProvider
from core.manager import HybridManager

class MockProvider:
    async def list_files(self, path: str = "/"):
        return [
            CloudItem(
                path="/test_file.txt",
                name="test_file.txt",
                type=ItemType.FILE,
                size=1024,
                modified_at=datetime.now()
            ),
            CloudItem(
                path="/test_folder",
                name="test_folder",
                type=ItemType.DIRECTORY,
                size=0,
                modified_at=datetime.now()
            )
        ]
    
    async def get_file_content(self, path: str, start: int = 0, end: int = None):
        yield b"Mock data content"

async def main():
    db_path = "test_state.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    
    db = StateDB(db_path)
    await db.initialize()
    
    # Use MockProvider for verification
    provider = MockProvider()
    manager = HybridManager(db, provider, "cache_test")
    
    print("--- Testing Sync ---")
    await manager.sync_directory("/")
    
    print("--- Testing List ---")
    children = await manager.get_children("/")
    for child in children:
        print(f"Child: {child['path']} ({child['type']}) - Status: {child['status']}")
    
    print("--- Testing Data Retrieval ---")
    data = await manager.get_file_bytes("/test_file.txt", 0, 100)
    print(f"Retrieved data: {data}")
    
    print("Verification complete!")

if __name__ == "__main__":
    asyncio.run(main())
