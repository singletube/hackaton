import aiosqlite
import logging
from typing import List, Optional
from datetime import datetime
from .models import ItemType, FileStatus, CloudItem, LocalState

logger = logging.getLogger(__name__)

class StateDB:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def initialize(self):
        """Initializes the database schema."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    path TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    size INTEGER DEFAULT 0,
                    modified_at TIMESTAMP,
                    inode INTEGER UNIQUE,
                    etag TEXT,
                    status TEXT NOT NULL,
                    local_path TEXT,
                    last_sync TIMESTAMP,
                    resource_id TEXT,
                    mime_type TEXT
                )
            """)
            # Create a trigger to auto-populate inode if NULL
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS auto_inode AFTER INSERT ON items
                WHEN NEW.inode IS NULL
                BEGIN
                    UPDATE items SET inode = NEW.rowid + 100 WHERE rowid = NEW.rowid;
                END;
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_parent_path ON items (path)")
            await db.commit()
            logger.info("Database initialized at %s", self.db_path)

    async def upsert_cloud_item(self, item: CloudItem, status: FileStatus = FileStatus.OFFLINE):
        """Adds or updates an item from the cloud."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO items (
                    path, name, type, size, modified_at, etag, status, resource_id, mime_type, last_sync
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name,
                    size=excluded.size,
                    modified_at=excluded.modified_at,
                    etag=excluded.etag,
                    resource_id=excluded.resource_id,
                    mime_type=excluded.mime_type,
                    last_sync=excluded.last_sync
            """, (
                item.path, item.name, item.type.value, item.size, 
                item.modified_at.isoformat(), item.etag, status.value, 
                item.resource_id, item.mime_type, datetime.now().isoformat()
            ))
            await db.commit()

    async def get_item_by_inode(self, inode: int) -> Optional[dict]:
        """Retrieves an item by its inode."""
        if inode == 1:
            return {"path": "/", "name": "", "type": ItemType.DIRECTORY, "inode": 1}
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM items WHERE inode = ?", (inode,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_item(self, path: str) -> Optional[dict]:
        """Retrieves a single item by path."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM items WHERE path = ?", (path,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_children(self, parent_path: str) -> List[dict]:
        """Lists items in a given directory."""
        # Simple path-based filtering for children
        # In a real app, we might store parent_id or use more complex globbing
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # This is a naive implementation; assuming path is like /a/b/c
            # and children are /a/b/c/d
            query = "SELECT * FROM items WHERE path LIKE ? AND path != ?"
            prefix = parent_path.rstrip('/') + '/%'
            async with db.execute(query, (prefix, parent_path)) as cursor:
                rows = await cursor.fetchall()
                # Filter to only direct children
                results = []
                parent_segments = [s for s in parent_path.split('/') if s]
                for row in rows:
                    child_segments = [s for s in row['path'].split('/') if s]
                    if len(child_segments) == len(parent_segments) + 1:
                        results.append(dict(row))
                return results

    async def update_status(self, path: str, status: FileStatus, local_path: Optional[str] = None, 
                           size: Optional[int] = None, modified_at: Optional[str] = None):
        """Updates the status and optional metadata of an item."""
        async with aiosqlite.connect(self.db_path) as db:
            if size is not None and modified_at is not None:
                await db.execute(
                    "UPDATE items SET status = ?, local_path = ?, size = ?, modified_at = ?, last_sync = ? WHERE path = ?",
                    (status.value, local_path, size, modified_at, datetime.now().isoformat(), path)
                )
            else:
                await db.execute(
                    "UPDATE items SET status = ?, local_path = ?, last_sync = ? WHERE path = ?",
                    (status.value, local_path, datetime.now().isoformat(), path)
                )
            await db.commit()

    async def delete_item(self, path: str):
        """Removes an item from the database."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM items WHERE path = ?", (path,))
            await db.commit()
            logger.debug("Deleted item from DB: %s", path)
