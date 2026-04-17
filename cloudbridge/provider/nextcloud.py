from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import aiohttp

from cloudbridge.models import CloudEntry, FileKind

from .base import ProviderError


class NextCloudProvider:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout_seconds: int = 30,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._dav_url = f"{self._base_url}/remote.php/dav/files/{quote(username)}"
        self._auth = aiohttp.BasicAuth(username, password)
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._owns_session = session is None

    async def __aenter__(self) -> "NextCloudProvider":
        await self._ensure_session()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session is not None and self._owns_session:
            await self._session.close()
        self._session = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                auth=self._auth, timeout=self._timeout
            )
        return self._session

    async def list_dir(self, path: str) -> list[CloudEntry]:
        session = await self._ensure_session()
        clean_path = path.strip("/")
        url = self._dav_item_url(clean_path)

        headers = {"Depth": "1"}
        async with session.request("PROPFIND", url, headers=headers) as resp:
            if resp.status not in (200, 207):
                text = await resp.text()
                raise ProviderError(f"NextCloud PROPFIND error {resp.status}: {text}")
            content = await resp.read()

        return self._parse_propfind(content, clean_path)

    def _parse_propfind(self, xml_content: bytes, parent_path: str) -> list[CloudEntry]:
        entries = []
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            raise ProviderError(f"Failed to parse WebDAV response: {e}")

        ns = {"d": "DAV:", "oc": "http://owncloud.org/dav"}
        
        for response in root.findall("d:response", ns):
            href_elem = response.find("d:href", ns)
            if href_elem is None or not href_elem.text:
                continue
            href = href_elem.text.rstrip("/")
            
            # Extract just the name from href
            name = href.split("/")[-1]
            
            # Skip the root directory itself in the response
            # If parent_path is empty, we are at the root, the root's href ends with username
            expected_root_name = parent_path.split("/")[-1] if parent_path else self._auth.login
            if name == expected_root_name or not name:
                continue

            propstat = response.find("d:propstat", ns)
            if propstat is None:
                continue
            prop = propstat.find("d:prop", ns)
            if prop is None:
                continue

            # Determine kind
            resourcetype = prop.find("d:resourcetype", ns)
            kind = FileKind.FILE
            if resourcetype is not None and resourcetype.find("d:collection", ns) is not None:
                kind = FileKind.DIRECTORY

            # Determine size
            size = 0
            getcontentlength = prop.find("d:getcontentlength", ns)
            if getcontentlength is not None and getcontentlength.text:
                size = int(getcontentlength.text)

            # Determine etag
            etag = None
            getetag = prop.find("d:getetag", ns)
            if getetag is not None and getetag.text:
                etag = getetag.text.strip('"')

            # Determine modified_at
            modified_at = None
            getlastmodified = prop.find("d:getlastmodified", ns)
            if getlastmodified is not None and getlastmodified.text:
                # e.g., 'Wed, 17 Apr 2026 12:00:00 GMT' -> convert to ISO 8601 if needed
                # For simplicity we'll just keep the raw string or parse it
                try:
                    dt = datetime.strptime(getlastmodified.text, "%a, %d %b %Y %H:%M:%S %Z")
                    modified_at = dt.isoformat() + "Z"
                except ValueError:
                    modified_at = getlastmodified.text

            path = f"{parent_path}/{name}" if parent_path else name
            
            entries.append(
                CloudEntry(
                    path=path,
                    name=name,
                    kind=kind,
                    size=size,
                    etag=etag,
                    modified_at=modified_at,
                )
            )

        return entries

    async def read_range(self, path: str, offset: int, size: int) -> bytes:
        if size <= 0:
            return b""

        clean_path = path.strip("/")
        url = self._dav_item_url(clean_path)
        end = offset + size - 1
        headers = {"Range": f"bytes={offset}-{end}"}

        session = await self._ensure_session()
        async with session.get(url, headers=headers) as resp:
            if resp.status in (200, 206):
                return await resp.read()
            if resp.status == 416:
                return b""
            text = await resp.text()
            raise ProviderError(
                f"NextCloud file read error {resp.status} for {path}: {text}"
            )

    async def ensure_dir(self, path: str) -> None:
        clean_path = path.strip("/")
        if not clean_path:
            return

        session = await self._ensure_session()
        url = self._dav_item_url(clean_path)
        async with session.request("MKCOL", url) as resp:
            if resp.status in (201, 405):
                return
            if resp.status >= 400:
                text = await resp.text()
                raise ProviderError(
                    f"NextCloud mkdir error {resp.status} for {path}: {text}"
                )

    async def upload_file(self, local_path: Path, cloud_path: str) -> None:
        clean_path = cloud_path.strip("/")
        data = await asyncio.to_thread(local_path.read_bytes)

        session = await self._ensure_session()
        url = self._dav_item_url(clean_path)
        async with session.put(url, data=data) as resp:
            if resp.status in (200, 201, 204):
                return
            text = await resp.text()
            raise ProviderError(
                f"NextCloud upload error {resp.status} for {cloud_path}: {text}"
            )

    async def download_file(self, cloud_path: str, local_path: Path) -> None:
        clean_path = cloud_path.strip("/")

        session = await self._ensure_session()
        url = self._dav_item_url(clean_path)
        async with session.get(url) as resp:
            if resp.status not in (200, 206):
                text = await resp.text()
                raise ProviderError(
                    f"NextCloud download error {resp.status} for {cloud_path}: {text}"
                )
            payload = await resp.read()

        local_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(local_path.write_bytes, payload)

    async def delete(self, path: str) -> None:
        clean_path = path.strip("/")
        if not clean_path:
            return

        session = await self._ensure_session()
        url = self._dav_item_url(clean_path)
        async with session.delete(url) as resp:
            if resp.status in (200, 204, 404):
                return
            if resp.status >= 400:
                text = await resp.text()
                raise ProviderError(
                    f"NextCloud delete error {resp.status} for {path}: {text}"
                )

    async def share_link(self, path: str) -> str:
        session = await self._ensure_session()
        # NextCloud uses OCS API for shares
        url = f"{self._base_url}/ocs/v1.php/apps/files_sharing/api/v1/shares"
        headers = {"OCS-APIRequest": "true"}
        data = {
            "path": f"/{path.strip('/')}",
            "shareType": "3",  # 3 = public link
        }
        
        async with session.post(url, headers=headers, data=data) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                raise ProviderError(f"NextCloud share error {resp.status}: {text}")
            
            content = await resp.read()
            try:
                root = ET.fromstring(content)
                url_elem = root.find(".//url")
                if url_elem is not None and url_elem.text:
                    return url_elem.text
                raise ProviderError("Could not find url in share response")
            except ET.ParseError as e:
                raise ProviderError(f"Failed to parse share response: {e}")

    def _dav_item_url(self, clean_path: str) -> str:
        if not clean_path:
            return self._dav_url
        return f"{self._dav_url}/{quote(clean_path, safe='/')}"
