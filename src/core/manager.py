import logging
import os
from pathlib import Path
from typing import List, Optional, AsyncIterator
from .database import StateDB
from .provider.base import StorageProvider
from .models import ItemType, FileStatus, CloudItem
from .xattr import set_placeholder_remote_path
from .ignore_list import is_ignored

logger = logging.getLogger(__name__)

class HybridManager:
    def __init__(self, db: StateDB, provider: StorageProvider, cache_dir: str, remote_root: str = "/"):
        self.db = db
        self.provider = provider
        self.cache_dir = cache_dir
        # Normalize remote_root: ensure leading slash, no trailing slash
        self.remote_root = "/" + remote_root.strip("/")
        if self.remote_root == "//":
            self.remote_root = "/"
            
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)

    async def sync_directory(self, remote_path: str = "/"):
        """Fetches remote state and updates the local database."""
        logger.info("Syncing directory: %s", remote_path)
        items = await self.provider.list_files(remote_path)
        
        for item in items:
            await self.db.upsert_cloud_item(item)
        
        logger.info("Synced %d items from %s", len(items), remote_path)

    async def get_children(self, path: str) -> List[dict]:
        """Returns directory contents, syncing if necessary."""
        # For simplicity, we sync on every readdir for now (or if empty)
        # In production, we'd use a TTL or event-based updates
        children = await self.db.get_children(path)
        if not children:
            await self.sync_directory(path)
            children = await self.db.get_children(path)
        return children

    async def get_file_bytes(self, path: str, offset: int, size: int) -> bytes:
        """Fetches file chunks. If not cached, downloads from cloud."""
        item = await self.db.get_item(path)
        if not item:
            raise FileNotFoundError(f"File not found in database: {path}")

        # If file is SYNCED, read from local cache
        if item['status'] == FileStatus.SYNCED and item['local_path']:
            if os.path.exists(item['local_path']):
                with open(item['local_path'], "rb") as f:
                    f.seek(offset)
                    return f.read(size)

        # Otherwise, download from provider (on-demand)
        # Note: This is a simplified version that doesn't cache yet
        # It just streams the requested range
        content = b""
        async for chunk in self.provider.get_file_content(path, start=offset, end=offset + size - 1):
            content += chunk
        
        return content

    async def upload_file(self, local_path: str, remote_path: str):
        """Uploads a local file and then 'de-hydrates' it to save space."""
        # Safety check: don't upload if it's already a stub
        if os.path.exists(local_path) and os.path.getsize(local_path) == 0:
            item = await self.db.get_item(remote_path)
            if item and item['status'] == FileStatus.OFFLINE.value:
                logger.debug("Safety: skipping upload of existing stub %s", local_path)
                return
            else:
                # If it's 0 bytes but NOT in DB as OFFLINE, it's either a new 
                # empty file or a corrupted state. We'll skip and log for safety.
                logger.warning("Safety: skipping upload of 0-byte file %s (not marked as stub in DB)", local_path)
                return

        logger.info("Uploading %s to %s", local_path, remote_path)
        await self.db.update_status(remote_path, FileStatus.SYNCING, local_path)
        
        try:
            await self.provider.upload_file(local_path, remote_path)
            
            # Capture real metadata before dehydration
            size = os.path.getsize(local_path)
            mtime_ts = os.path.getmtime(local_path)
            from datetime import datetime
            mtime = datetime.fromtimestamp(mtime_ts)
            mtime_iso = mtime.isoformat()
            logger.debug("Captured metadata for %s: size=%d, mtime=%s", local_path, size, mtime_iso)
            await self.db.upsert_cloud_item(
                CloudItem(
                    path=remote_path,
                    name=os.path.basename(remote_path),
                    type=ItemType.FILE,
                    size=size,
                    modified_at=mtime,
                ),
                status=FileStatus.OFFLINE,
            )
            
            # De-hydration: truncate local file to 0 bytes
            logger.info("De-hydrating (stubbing) local file: %s (cloud size: %d)", local_path, size)
            with open(local_path, "wb") as f:
                f.truncate(0)
            set_placeholder_remote_path(local_path, remote_path)
            
            await self.db.update_status(remote_path, FileStatus.OFFLINE, local_path, 
                                      size=size, modified_at=mtime_iso)
            logger.info("Successfully uploaded and stubbed %s", remote_path)
        except Exception as e:
            logger.error("Failed to upload %s: %s", remote_path, e)
            await self.db.update_status(remote_path, FileStatus.ERROR)

    async def delete_remote_file(self, remote_path: str):
        """Deletes a file from the cloud and removes its entry from the DB."""
        logger.info("Syncing deletion to cloud: %s", remote_path)
        try:
            await self.provider.delete_file(remote_path)
            await self.db.delete_item(remote_path)
            logger.info("Successfully deleted remote: %s", remote_path)
        except Exception as e:
            logger.error("Failed to delete remote file %s: %s", remote_path, e)

    async def move_remote_file(self, src_path: str, dest_path: str):
        """Moves a file in the cloud and updates the local DB entry."""
        logger.info("Syncing move to cloud: %s -> %s", src_path, dest_path)
        try:
            await self.provider.move_file(src_path, dest_path)
            # Update DB: Delete old, Upsert new? 
            # For simplicity, we delete old and let next sync pick up new
            await self.db.delete_item(src_path)
            # Or we could do a rename in DB if we had that method
            logger.info("Successfully moved remote: %s", dest_path)
        except Exception as e:
            logger.error("Failed to move remote file %s: %s", src_path, e)

    async def download_file_to_path(self, remote_path: str, local_path: str):
        """Downloads a remote file to an exact local path using an atomic replace."""
        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = destination.with_name(f".{destination.name}.cloudbridge-download")

        logger.info("Downloading %s to %s", remote_path, destination)
        try:
            with tmp_path.open("wb") as f:
                async for chunk in self.provider.get_file_content(remote_path):
                    if chunk:
                        f.write(chunk)
            tmp_path.replace(destination)
            logger.info("Downloaded real file to %s", destination)
        except Exception:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            raise

    async def prune_remote_only_files(self, local_root: str):
        """Removes files from the cloud that do not exist locally."""
        logger.info("Pruning cloud files not present in %s", local_root)
        remote_items = await self.provider.get_all_files_recursive(self.remote_root)
        
        for item in remote_items:
            # Determine expected local path
            rel_path = os.path.relpath(item.path, self.remote_root)
            local_path = os.path.join(local_root, rel_path)
            
            # If item not found locally (even as 0-byte stub)
            if not os.path.exists(local_path):
                logger.info("Pruning orphan cloud file: %s", item.path)
                await self.delete_remote_file(item.path)

    async def bootstrap_local_sync(self, local_root: str):
        """Walks the local directory and ensures all items exist in the cloud."""
        logger.info("Starting initial bootstrap sync for %s", local_root)
        uploaded = 0
        skipped = 0
        
        for root, dirs, files in os.walk(local_root):
            # 1. Sync Directories
            for d in list(dirs):
                local_dir_path = os.path.join(root, d)
                relative_path = os.path.relpath(local_dir_path, local_root)
                remote_path = os.path.join(self.remote_root, relative_path).replace(os.sep, '/')
                if is_ignored(remote_path):
                    logger.info("Bootstrap: skipping ignored directory %s", remote_path)
                    dirs.remove(d)
                    skipped += 1
                    continue
                
                logger.info("Bootstrap: ensuring remote directory %s", remote_path)
                await self.provider.create_directory(remote_path)
            
            # 2. Sync Files
            for f in files:
                local_file_path = os.path.join(root, f)
                relative_path = os.path.relpath(local_file_path, local_root)
                remote_path = os.path.join(self.remote_root, relative_path).replace(os.sep, '/')
                if is_ignored(remote_path):
                    logger.info("Bootstrap: skipping ignored file %s", remote_path)
                    skipped += 1
                    continue
                try:
                    if os.path.getsize(local_file_path) == 0:
                        logger.info("Bootstrap: skipping 0-byte local placeholder %s", local_file_path)
                        skipped += 1
                        continue
                except OSError as e:
                    logger.warning("Bootstrap: cannot stat %s: %s", local_file_path, e)
                    skipped += 1
                    continue
                
                # Check if file exists in DB and is already handled (SYNCED or OFFLINE stub)
                item = await self.db.get_item(remote_path)
                already_synced = item and (item['status'] == FileStatus.SYNCED.value or 
                                          item['status'] == FileStatus.OFFLINE.value)
                
                if not already_synced:
                    logger.info("Bootstrap: uploading new file %s", remote_path)
                    await self.upload_file(local_file_path, remote_path)
                    uploaded += 1
                else:
                    skipped += 1

        logger.info("Bootstrap complete for %s: uploaded=%d skipped=%d", local_root, uploaded, skipped)

    async def ensure_placeholder(self, path: str):
        pass
