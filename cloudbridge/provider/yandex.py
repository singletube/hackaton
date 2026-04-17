from __future__ import annotations

from typing import Any, Optional

import aiohttp

from cloudbridge.models import CloudEntry, FileKind

from .base import ProviderError


class YandexDiskProvider:
    BASE_URL = "https://cloud-api.yandex.net/v1/disk"

    def __init__(
        self,
        token: str,
        *,
        timeout_seconds: int = 30,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self._token = token
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._owns_session = session is None

    async def __aenter__(self) -> "YandexDiskProvider":
        await self._ensure_session()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session is not None and self._owns_session:
            await self._session.close()
        self._session = None

    async def list_dir(self, path: str) -> list[CloudEntry]:
        entries: list[CloudEntry] = []
        offset = 0
        limit = 1000

        while True:
            payload = await self._request_json(
                "GET",
                "/resources",
                params={
                    "path": path,
                    "limit": str(limit),
                    "offset": str(offset),
                    "fields": (
                        "_embedded.items.name,"
                        "_embedded.items.path,"
                        "_embedded.items.type,"
                        "_embedded.items.size,"
                        "_embedded.items.md5,"
                        "_embedded.items.modified,"
                        "_embedded.total"
                    ),
                },
            )
            embedded = payload.get("_embedded") or {}
            items = embedded.get("items") or []
            for item in items:
                kind = self._map_kind(item.get("type"))
                if kind is None:
                    continue
                entries.append(
                    CloudEntry(
                        path=str(item["path"]),
                        name=str(item["name"]),
                        kind=kind,
                        size=item.get("size"),
                        etag=item.get("md5"),
                        modified_at=item.get("modified"),
                    )
                )

            total = int(embedded.get("total", 0))
            offset += len(items)
            if not items or offset >= total:
                break

        return entries

    async def read_range(self, path: str, offset: int, size: int) -> bytes:
        if size <= 0:
            return b""

        link_payload = await self._request_json(
            "GET",
            "/resources/download",
            params={"path": path},
        )
        href = link_payload.get("href")
        if not href:
            raise ProviderError(f"Missing download URL for path: {path}")

        end = offset + size - 1
        headers = {"Range": f"bytes={offset}-{end}"}
        session = await self._ensure_session()
        async with session.get(href, headers=headers) as resp:
            if resp.status in (200, 206):
                return await resp.read()
            if resp.status == 416:
                return b""
            text = await resp.text()
            raise ProviderError(
                f"Yandex file read error {resp.status} for {path}: {text}"
            )

    async def share_link(self, path: str) -> str:
        # Step 1: Publish the resource
        await self._request_json(
            "PUT",
            "/resources/publish",
            params={"path": path},
        )
        # Step 2: Get the resource to retrieve the public URL
        payload = await self._request_json(
            "GET",
            "/resources",
            params={"path": path, "fields": "public_url"},
        )
        public_url = payload.get("public_url")
        if not public_url:
            raise ProviderError(f"Failed to get public URL for path: {path}")
        return public_url

    async def _request_json(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        session = await self._ensure_session()
        url = f"{self.BASE_URL}{endpoint}"
        headers = {"Authorization": f"OAuth {self._token}"}
        async with session.request(method, url, headers=headers, params=params) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise ProviderError(
                    f"Yandex API error {resp.status} for {endpoint}: {text}"
                )
            return await resp.json()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    @staticmethod
    def _map_kind(value: Any) -> Optional[FileKind]:
        if value == "dir":
            return FileKind.DIRECTORY
        if value == "file":
            return FileKind.FILE
        return None
