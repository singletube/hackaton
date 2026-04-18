import pyfuse3
import stat
import errno
import logging
import os
from typing import AsyncGenerator
from pyfuse3 import FUSEError
from ..core.manager import HybridManager
from ..core.models import ItemType

logger = logging.getLogger(__name__)

class CloudBridgeFS(pyfuse3.Operations):
    def __init__(self, manager: HybridManager):
        super().__init__()
        self.manager = manager
        # In-memory lookup count tracking (simplified for now)
        self.lookup_counts = {}

    async def getattr(self, inode: int, ctx=None):
        """Returns attributes for an inode."""
        if inode == 1:
            # Root inode maps to the user-selected remote_root
            item = await self.manager.db.get_item(self.manager.remote_root)
            if not item:
                # If remote_root not in DB, return a generic directory
                item = {"path": self.manager.remote_root, "name": "", "type": ItemType.DIRECTORY, "inode": 1}
        else:
            item = await self.manager.db.get_item_by_inode(inode)
            
        if not item:
            raise FUSEError(errno.ENOENT)

        entry = pyfuse3.EntryAttributes()
        entry.st_ino = inode
        
        if item['type'] == ItemType.DIRECTORY:
            entry.st_mode = (stat.S_IFDIR | 0o755)
            entry.st_size = 0
        else:
            entry.st_mode = (stat.S_IFREG | 0o644)
            entry.st_size = item.get('size', 0)
        
        logger.debug("getattr inode %d (%s): size=%d", inode, item['path'], entry.st_size)

        # Timestamps
        mtime = 0
        try:
            m_at = item.get('modified_at')
            if isinstance(m_at, str):
                from datetime import datetime
                # Handle ISO format from SQLite
                dt = datetime.fromisoformat(m_at.replace('Z', '+00:00'))
                mtime = int(dt.timestamp())
            elif m_at:
                mtime = int(m_at.timestamp())
        except Exception as e:
            logger.debug("Failed to parse mtime for %s: %s", item['path'], e)
            
        entry.st_atime_ns = mtime * 1_000_000_000
        entry.st_mtime_ns = mtime * 1_000_000_000
        entry.st_ctime_ns = mtime * 1_000_000_000
        
        entry.st_gid = os.getgid()
        entry.st_uid = os.getuid()
        entry.st_blksize = 4096
        entry.st_blocks = (entry.st_size + 511) // 512
        
        return entry

    async def lookup(self, parent_inode: int, name: bytes, ctx=None):
        """Looks up a name in a parent directory."""
        name_str = name.decode('utf-8')
        if parent_inode == 1:
            parent_path = self.manager.remote_root
        else:
            parent = await self.manager.db.get_item_by_inode(parent_inode)
            if not parent:
                raise FUSEError(errno.ENOENT)
            parent_path = parent['path']
        
        target_path = os.path.join(parent_path, name_str).replace('\\', '/')
        if target_path.startswith('//'):
            target_path = target_path[1:]

        item = await self.manager.db.get_item(target_path)
        if not item:
            raise FUSEError(errno.ENOENT)

        return await self.getattr(item['inode'])

    async def opendir(self, inode: int, ctx):
        return inode

    async def readdir(self, inode: int, off: int, token):
        """Lists directory entries."""
        if inode == 1:
            parent_path = self.manager.remote_root
        else:
            parent = await self.manager.db.get_item_by_inode(inode)
            if not parent:
                raise FUSEError(errno.ENOENT)
            parent_path = parent['path']

        # Sync directory if needed
        children = await self.manager.get_children(parent_path)
        
        # Add '.' and '..'
        entries = [
            ('.', inode),
            ('..', 1)  # Simplified, should be real parent
        ]
        for child in children:
            entries.append((child['name'], child['inode']))

        for i, (name, child_inode) in enumerate(entries[off:], start=off):
            if not pyfuse3.readdir_reply(token, name.encode('utf-8'), 
                                       await self.getattr(child_inode), i + 1):
                break

    async def open(self, inode: int, flags, ctx):
        """Opens a file (read-only for now)."""
        if flags & os.O_WRONLY or flags & os.O_RDWR:
            raise FUSEError(errno.EROFS)
        return pyfuse3.FileInfo(fh=inode)

    async def read(self, inode: int, off: int, size: int, fi):
        """Reads file data on-demand."""
        item = await self.manager.db.get_item_by_inode(inode)
        if not item:
            raise FUSEError(errno.ENOENT)
        
        # Fetch data via manager (handles cloud download if needed)
        try:
            data = await self.manager.get_file_bytes(item['path'], off, size)
            return data
        except Exception as e:
            logger.error("Failed to read file %s: %s", item['path'], e)
            raise FUSEError(errno.EIO)
