from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

from ..errors import ConflictError, ProviderAuthenticationError, ProviderError, ResourceMissingError
from ..models import EntryKind, RemoteEntry
from ..paths import basename, normalize_virtual_path, parent_path
from .base import CloudProvider


class YandexDiskProvider(CloudProvider):
    name = "yandex"
    _api_base = "https://cloud-api.yandex.net/v1/disk"

    def __init__(self, token: str, *, request_timeout: float = 60.0) -> None:
        if not token:
            raise ProviderAuthenticationError("YANDEX_DISK_TOKEN is required for the Yandex provider.")
        timeout = aiohttp.ClientTimeout(total=request_timeout)
        self._session = aiohttp.ClientSession(
            headers={"Authorization": f"OAuth {token}"},
            timeout=timeout,
            raise_for_status=False,
        )

    async def close(self) -> None:
        await self._session.close()

    async def list_directory(self, path: str) -> list[RemoteEntry]:
        normalized = normalize_virtual_path(path)
        offset = 0
        limit = 200
        items: list[RemoteEntry] = []
        while True:
            payload = await self._request_json(
                "GET",
                "/resources",
                params={
                    "path": self._disk_path(normalized),
                    "offset": offset,
                    "limit": limit,
                    "fields": "path,type,name,size,modified,md5,etag,public_url,_embedded.items.path,_embedded.items.type,_embedded.items.name,_embedded.items.size,_embedded.items.modified,_embedded.items.md5,_embedded.items.etag,_embedded.items.public_url,_embedded.offset,_embedded.limit,_embedded.total",
                },
            )
            embedded = payload.get("_embedded") or {}
            batch = embedded.get("items") or []
            items.extend(self._resource_to_entry(entry) for entry in batch)
            offset += len(batch)
            total = int(embedded.get("total", len(batch)))
            if offset >= total or not batch:
                break
        return items

    async def stat(self, path: str) -> RemoteEntry | None:
        normalized = normalize_virtual_path(path)
        if normalized == "/":
            return RemoteEntry(path="/", name="", parent_path="/", kind=EntryKind.DIRECTORY)
        try:
            payload = await self._request_json(
                "GET",
                "/resources",
                params={
                    "path": self._disk_path(normalized),
                    "fields": "path,type,name,size,modified,md5,etag,public_url",
                },
            )
        except ResourceMissingError:
            return None
        return self._resource_to_entry(payload)

    async def ensure_directory(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        if normalized == "/":
            return
        segments = normalized.strip("/").split("/")
        current = ""
        for segment in segments:
            current = f"{current}/{segment}" if current else f"/{segment}"
            try:
                await self._request_empty(
                    "PUT",
                    "/resources",
                    params={"path": self._disk_path(current)},
                    expected={201, 409},
                )
            except ConflictError:
                continue

    async def upload_file(self, local_path: str, remote_path: str, overwrite: bool = True) -> RemoteEntry:
        normalized = normalize_virtual_path(remote_path)
        await self.ensure_directory(parent_path(normalized))
        upload_descriptor = await self._request_json(
            "GET",
            "/resources/upload",
            params={"path": self._disk_path(normalized), "overwrite": str(overwrite).lower()},
        )
        upload_url = upload_descriptor["href"]
        data = Path(local_path).read_bytes()
        async with self._session.put(upload_url, data=data) as response:
            if response.status not in {200, 201, 202}:
                text = await response.text()
                raise ProviderError(f"Upload failed with status {response.status}: {text}")
        entry = await self.stat(normalized)
        if entry is None:
            raise ProviderError(f"Uploaded resource is not visible yet: {normalized}")
        return entry

    async def download_file(self, remote_path: str, local_path: str) -> None:
        normalized = normalize_virtual_path(remote_path)
        descriptor = await self._request_json(
            "GET",
            "/resources/download",
            params={"path": self._disk_path(normalized)},
        )
        href = descriptor["href"]
        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with self._session.get(href) as response:
            if response.status != 200:
                text = await response.text()
                raise ProviderError(f"Download failed with status {response.status}: {text}")
            with destination.open("wb") as file_handle:
                async for chunk in response.content.iter_chunked(256 * 1024):
                    file_handle.write(chunk)

    async def delete(self, path: str, permanently: bool = True) -> None:
        normalized = normalize_virtual_path(path)
        await self._request_empty(
            "DELETE",
            "/resources",
            params={"path": self._disk_path(normalized), "permanently": str(permanently).lower()},
            expected={202, 204},
        )

    async def move(self, source_path: str, target_path: str, overwrite: bool = True) -> None:
        source = normalize_virtual_path(source_path)
        target = normalize_virtual_path(target_path)
        await self.ensure_directory(parent_path(target))
        await self._request_empty(
            "POST",
            "/resources/move",
            params={
                "from": self._disk_path(source),
                "path": self._disk_path(target),
                "overwrite": str(overwrite).lower(),
            },
            expected={201, 202},
        )

    async def publish(self, path: str) -> str:
        normalized = normalize_virtual_path(path)
        await self._request_empty(
            "PUT",
            "/resources/publish",
            params={"path": self._disk_path(normalized)},
            expected={200, 201, 202},
        )
        entry = await self.stat(normalized)
        if entry is None or not entry.public_url:
            raise ProviderError(f"Failed to publish {normalized}")
        return entry.public_url

    def _disk_path(self, path: str) -> str:
        normalized = normalize_virtual_path(path)
        return "disk:/" if normalized == "/" else f"disk:{normalized}"

    async def _request_json(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        expected: set[int] | None = None,
    ) -> dict[str, Any]:
        expected_codes = expected or {200, 201, 202}
        async with self._session.request(method, f"{self._api_base}{endpoint}", params=params) as response:
            if response.status not in expected_codes:
                await self._raise_for_response(response)
            if response.status == 204:
                return {}
            return await response.json()

    async def _request_empty(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        expected: set[int] | None = None,
    ) -> None:
        expected_codes = expected or {200, 201, 202, 204}
        async with self._session.request(method, f"{self._api_base}{endpoint}", params=params) as response:
            if response.status not in expected_codes:
                await self._raise_for_response(response)
            if response.status == 202:
                payload = await response.json()
                href = payload.get("href")
                if href:
                    await self._await_operation(href)

    async def _await_operation(self, href: str, *, timeout: float = 60.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            async with self._session.get(href) as response:
                if response.status != 200:
                    text = await response.text()
                    raise ProviderError(f"Operation polling failed with status {response.status}: {text}")
                payload = await response.json()
            status = payload.get("status")
            if status == "success":
                return
            if status == "failed":
                raise ProviderError(f"Remote operation failed: {payload}")
            if asyncio.get_running_loop().time() >= deadline:
                raise ProviderError(f"Remote operation timed out: {payload}")
            await asyncio.sleep(0.5)

    async def _raise_for_response(self, response: aiohttp.ClientResponse) -> None:
        text = await response.text()
        if response.status in {401, 403}:
            raise ProviderAuthenticationError(text or "Provider authentication failed.")
        if response.status == 404:
            raise ResourceMissingError(text or "Remote resource not found.")
        if response.status == 409:
            raise ConflictError(text or "Remote resource conflict.")
        raise ProviderError(f"Provider request failed with status {response.status}: {text}")

    def _resource_to_entry(self, payload: dict[str, Any]) -> RemoteEntry:
        raw_path = str(payload.get("path", ""))
        normalized = normalize_virtual_path(raw_path.replace("disk:", "", 1))
        modified = payload.get("modified")
        modified_at = datetime.fromisoformat(modified.replace("Z", "+00:00")) if modified else None
        kind = EntryKind.DIRECTORY if payload.get("type") == "dir" else EntryKind.FILE
        return RemoteEntry(
            path=normalized,
            name=payload.get("name") or basename(normalized),
            parent_path=parent_path(normalized),
            kind=kind,
            size=payload.get("size"),
            modified_at=modified_at,
            etag=payload.get("etag"),
            checksum=payload.get("md5"),
            public_url=payload.get("public_url"),
        )
