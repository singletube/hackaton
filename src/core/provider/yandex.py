import asyncio
import aiohttp
import logging
from typing import List, AsyncIterator, Optional
from datetime import datetime
from .base import StorageProvider
from ..models import CloudItem, ItemType

logger = logging.getLogger(__name__)

class YandexDiskProvider(StorageProvider):
    BASE_URL = "https://cloud-api.yandex.net/v1/disk"

    def __init__(self, token: str):
        self.token = token
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers={
                "Authorization": f"OAuth {self.token}"
            })
        return self.session

    async def list_files(self, path: str = "/") -> List[CloudItem]:
        """Lists files and folders in the remote path."""
        session = await self._get_session()
        params = {
            "path": path,
            "limit": 1000,  # Adjustable
            "fields": "_embedded.items.name,_embedded.items.path,_embedded.items.type,_embedded.items.size,_embedded.items.modified,_embedded.items.resource_id"
        }
        
        async with session.get(f"{self.BASE_URL}/resources", params=params) as response:
            if response.status != 200:
                error_data = await response.json()
                logger.error("Failed to list files: %s", error_data)
                return []
            
            data = await response.json()
            logger.info("API Response: %s", data)
            items = data.get("_embedded", {}).get("items", [])
            
            cloud_items = []
            for item in items:
                # Yandex paths are often 'disk:/path/to/file'
                clean_path = item['path'].replace("disk:", "", 1)
                
                cloud_items.append(CloudItem(
                    path=clean_path,
                    name=item['name'],
                    type=ItemType.DIRECTORY if item['type'] == 'dir' else ItemType.FILE,
                    size=item.get('size', 0),
                    modified_at=datetime.fromisoformat(item['modified'].replace('Z', '+00:00')),
                    resource_id=item.get('resource_id')
                ))
            return cloud_items

    async def get_file_content(self, path: str, start: int = 0, end: Optional[int] = None) -> AsyncIterator[bytes]:
        """Downloads file content as an async stream, optionally with a range."""
        session = await self._get_session()
        
        # 1. Get download link
        async with session.get(f"{self.BASE_URL}/resources/download", params={"path": path}) as response:
            if response.status != 200:
                logger.error("Failed to get download link for %s", path)
                return
            data = await response.json()
            download_url = data['href']

        # 2. Download the actual content
        headers = {}
        if end is not None:
            headers["Range"] = f"bytes={start}-{end}"
        elif start > 0:
            headers["Range"] = f"bytes={start}-"

        async with session.get(download_url, headers=headers) as response:
            if response.status not in (200, 206):
                logger.error("Failed to download content from %s", download_url)
                return
            
            async for chunk in response.content.iter_any():
                yield chunk

    async def create_directory(self, path: str):
        """Creates a directory in the remote storage."""
        session = await self._get_session()
        async with session.put(f"{self.BASE_URL}/resources", params={"path": path}) as response:
            if response.status not in (201, 409):  # 409 means already exists
                error_data = await response.json()
                logger.error("Failed to create directory %s: %s", path, error_data)
                return False
            return True

    async def upload_file(self, local_path: str, remote_path: str):
        """Uploads a local file to the remote storage."""
        session = await self._get_session()
        
        # 1. Get upload URL
        async with session.get(f"{self.BASE_URL}/resources/upload", params={"path": remote_path, "overwrite": "true"}) as response:
            if response.status != 200:
                error_data = await response.json()
                logger.error("Failed to get upload URL for %s: %s", remote_path, error_data)
                raise RuntimeError(f"Failed to get upload URL for {remote_path}: {error_data}")
            data = await response.json()
            upload_url = data['href']

        # 2. Upload file content
        with open(local_path, "rb") as f:
            async with session.put(upload_url, data=f) as response:
                if response.status not in (201, 202):
                    logger.error("Failed to upload content for %s", remote_path)
                    raise RuntimeError(f"Failed to upload content for {remote_path}: HTTP {response.status}")
        return True

    async def delete_file(self, remote_path: str):
        """Deletes a resource from Yandex.Disk (moves to Trash)."""
        logger.info("Deleting remote resource: %s", remote_path)
        session = await self._get_session()
        url = f"{self.BASE_URL}/resources"
        params = {"path": remote_path}
        
        async with session.delete(url, params=params) as resp:
            if resp.status not in (202, 204):
                try:
                    error_data = await resp.json()
                    logger.error("Failed to delete %s: %s", remote_path, error_data)
                except Exception:
                    logger.error("Failed to delete %s: Status %d", remote_path, resp.status)

    async def move_file(self, src_path: str, dest_path: str):
        """Moves/renames a resource on Yandex.Disk."""
        logger.info("Moving remote resource: %s -> %s", src_path, dest_path)
        session = await self._get_session()
        url = f"{self.BASE_URL}/resources/move"
        params = {"from": src_path, "path": dest_path, "overwrite": "true"}
        
        async with session.post(url, params=params) as resp:
            if resp.status not in (201, 202):
                error_data = await resp.json()
                logger.error("Failed to move %s: %s", src_path, error_data)

    async def get_resource(self, path: str, fields: Optional[str] = None) -> dict:
        """Gets resource metadata from Yandex.Disk."""
        session = await self._get_session()
        params = {"path": path}
        if fields:
            params["fields"] = fields

        async with session.get(f"{self.BASE_URL}/resources", params=params) as response:
            if response.status != 200:
                try:
                    error_data = await response.json()
                except Exception:
                    error_data = {"status": response.status}
                raise RuntimeError(f"Failed to get resource {path}: {error_data}")
            return await response.json()

    async def publish_resource(self, path: str) -> str:
        """Publishes a resource and returns its public read-only URL."""
        session = await self._get_session()

        async with session.put(f"{self.BASE_URL}/resources/publish", params={"path": path}) as response:
            if response.status not in (200, 201, 202):
                try:
                    error_data = await response.json()
                except Exception:
                    error_data = {"status": response.status}
                raise RuntimeError(f"Failed to publish {path}: {error_data}")

        for _ in range(5):
            resource = await self.get_resource(path, fields="public_url")
            public_url = resource.get("public_url")
            if public_url:
                return public_url
            await asyncio.sleep(0.5)
        raise RuntimeError(f"Yandex.Disk did not return public_url for {path}")

    async def get_all_files_recursive(self, remote_root: str) -> List[CloudItem]:
        """Deep crawl of the remote directory structure."""
        all_items = []
        stack = [remote_root]
        
        while stack:
            current_path = stack.pop()
            items = await self.list_files(current_path)
            for item in items:
                all_items.append(item)
                if item.type == ItemType.DIRECTORY:
                    stack.append(item.path)
        
        return all_items

    async def close(self):
        if self.session:
            await self.session.close()
