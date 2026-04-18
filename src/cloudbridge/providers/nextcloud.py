from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree

import aiohttp

from ..errors import ConflictError, ProviderAuthenticationError, ProviderError, ResourceMissingError
from ..models import EntryKind, RemoteEntry
from ..paths import basename, normalize_virtual_path, parent_path
from .base import CloudProvider

_DAV_NAMESPACE = "{DAV:}"
_OC_NAMESPACE = "{http://owncloud.org/ns}"


class NextcloudProvider(CloudProvider):
    name = "nextcloud"
    _propfind_body = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
  <d:prop>
    <d:getlastmodified />
    <d:getetag />
    <d:getcontentlength />
    <d:resourcetype />
    <oc:size />
    <oc:checksums />
  </d:prop>
</d:propfind>
"""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        request_timeout: float = 60.0,
    ) -> None:
        if not base_url or not username or not password:
            raise ProviderAuthenticationError(
                "NEXTCLOUD_URL, NEXTCLOUD_USERNAME, and NEXTCLOUD_PASSWORD are required for the Nextcloud provider."
            )
        timeout = aiohttp.ClientTimeout(total=request_timeout)
        self._base_url = base_url.rstrip("/")
        self._session = aiohttp.ClientSession(
            auth=aiohttp.BasicAuth(username, password),
            timeout=timeout,
            raise_for_status=False,
            headers={"Accept": "application/json, text/plain, */*"},
        )
        self._user_id: str | None = None

    async def close(self) -> None:
        await self._session.close()

    async def list_directory(self, path: str) -> list[RemoteEntry]:
        normalized = normalize_virtual_path(path)
        entries = await self._propfind(normalized, depth=1)
        return [entry for entry in entries if entry.path != normalized]

    async def stat(self, path: str) -> RemoteEntry | None:
        normalized = normalize_virtual_path(path)
        try:
            entries = await self._propfind(normalized, depth=0)
        except ResourceMissingError:
            return None
        return entries[0] if entries else None

    async def ensure_directory(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        if normalized == "/":
            return
        current = ""
        for segment in normalized.strip("/").split("/"):
            current = f"{current}/{segment}" if current else f"/{segment}"
            await self._request_empty(
                "MKCOL",
                await self._dav_url(current),
                expected={201, 405},
            )

    async def upload_file(self, local_path: str, remote_path: str, overwrite: bool = True) -> RemoteEntry:
        normalized = normalize_virtual_path(remote_path)
        await self.ensure_directory(parent_path(normalized))
        headers: dict[str, str] = {"Content-Type": "application/octet-stream"}
        if not overwrite:
            headers["If-None-Match"] = "*"
        async with self._session.put(await self._dav_url(normalized), data=Path(local_path).read_bytes(), headers=headers) as response:
            if response.status not in {200, 201, 204}:
                await self._raise_for_response(response)
        entry = await self.stat(normalized)
        if entry is None:
            raise ProviderError(f"Uploaded resource is not visible yet: {normalized}")
        return entry

    async def download_file(self, remote_path: str, local_path: str) -> None:
        normalized = normalize_virtual_path(remote_path)
        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with self._session.get(await self._dav_url(normalized)) as response:
            if response.status != 200:
                await self._raise_for_response(response)
            with destination.open("wb") as file_handle:
                async for chunk in response.content.iter_chunked(256 * 1024):
                    file_handle.write(chunk)

    async def delete(self, path: str, permanently: bool = True) -> None:
        normalized = normalize_virtual_path(path)
        await self._request_empty("DELETE", await self._dav_url(normalized), expected={204})

    async def move(self, source_path: str, target_path: str, overwrite: bool = True) -> None:
        source = normalize_virtual_path(source_path)
        target = normalize_virtual_path(target_path)
        await self.ensure_directory(parent_path(target))
        await self._request_empty(
            "MOVE",
            await self._dav_url(source),
            headers={
                "Destination": await self._dav_url(target),
                "Overwrite": "T" if overwrite else "F",
            },
            expected={201, 204},
        )

    async def publish(self, path: str) -> str:
        normalized = normalize_virtual_path(path)
        existing = await self._find_existing_public_share(normalized)
        if existing:
            return existing
        payload = await self._request_ocs_json(
            "POST",
            "/ocs/v2.php/apps/files_sharing/api/v1/shares",
            data={
                "path": normalized,
                "shareType": "3",
                "permissions": "1",
            },
        )
        url = self._extract_share_url(payload)
        if not url:
            raise ProviderError(f"Failed to publish {normalized}")
        return url

    async def _resolve_user_id(self) -> str:
        if self._user_id is not None:
            return self._user_id
        payload = await self._request_ocs_json("GET", "/ocs/v1.php/cloud/user")
        user_id = None
        if isinstance(payload, dict):
            user_id = payload.get("id") or payload.get("userId")
        if not user_id:
            raise ProviderError("Nextcloud did not return the current user id.")
        self._user_id = str(user_id)
        return self._user_id

    async def _dav_url(self, path: str) -> str:
        user_id = quote(await self._resolve_user_id(), safe="")
        normalized = normalize_virtual_path(path)
        if normalized == "/":
            return f"{self._base_url}/remote.php/dav/files/{user_id}/"
        return f"{self._base_url}/remote.php/dav/files/{user_id}{quote(normalized, safe='/')}"

    async def _dav_root_path(self) -> str:
        return unquote(urlparse(await self._dav_url("/")).path).rstrip("/")

    async def _propfind(self, path: str, *, depth: int) -> list[RemoteEntry]:
        headers = {
            "Depth": str(depth),
            "Content-Type": "application/xml; charset=utf-8",
        }
        async with self._session.request(
            "PROPFIND",
            await self._dav_url(path),
            data=self._propfind_body,
            headers=headers,
        ) as response:
            if response.status == 404:
                raise ResourceMissingError(f"Remote resource not found: {path}")
            if response.status != 207:
                await self._raise_for_response(response)
            text = await response.text()
        return await self._parse_multistatus(text)

    async def _parse_multistatus(self, payload: str) -> list[RemoteEntry]:
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as error:
            raise ProviderError(f"Failed to parse Nextcloud WebDAV response: {error}") from error

        entries: list[RemoteEntry] = []
        dav_root_path = await self._dav_root_path()
        for response in root.findall(f"{_DAV_NAMESPACE}response"):
            href = response.findtext(f"{_DAV_NAMESPACE}href")
            if not href:
                continue
            props = None
            for propstat in response.findall(f"{_DAV_NAMESPACE}propstat"):
                status = propstat.findtext(f"{_DAV_NAMESPACE}status", "")
                if " 200 " not in status:
                    continue
                props = propstat.find(f"{_DAV_NAMESPACE}prop")
                if props is not None:
                    break
            if props is None:
                continue
            entries.append(self._entry_from_propfind(href, props, dav_root_path))
        return entries

    def _entry_from_propfind(self, href: str, props: ElementTree.Element, dav_root_path: str) -> RemoteEntry:
        path = self._href_to_virtual_path(href, dav_root_path)
        resource_type = props.find(f"{_DAV_NAMESPACE}resourcetype")
        kind = EntryKind.FILE
        if resource_type is not None and resource_type.find(f"{_DAV_NAMESPACE}collection") is not None:
            kind = EntryKind.DIRECTORY

        modified_raw = props.findtext(f"{_DAV_NAMESPACE}getlastmodified")
        modified_at = parsedate_to_datetime(modified_raw) if modified_raw else None

        size_raw = props.findtext(f"{_OC_NAMESPACE}size") or props.findtext(f"{_DAV_NAMESPACE}getcontentlength")
        size = int(size_raw) if size_raw and size_raw.isdigit() else None
        if kind is EntryKind.DIRECTORY:
            size = None

        etag_raw = props.findtext(f"{_DAV_NAMESPACE}getetag")
        etag = etag_raw.strip('"') if etag_raw else None

        checksums = props.findtext(f"{_OC_NAMESPACE}checksums")
        checksum = self._extract_checksum(checksums)

        return RemoteEntry(
            path=path,
            name="" if path == "/" else basename(path),
            parent_path=parent_path(path),
            kind=kind,
            size=size,
            modified_at=modified_at,
            etag=etag,
            checksum=checksum,
        )

    def _href_to_virtual_path(self, href: str, dav_root_path: str) -> str:
        href_path = unquote(urlparse(href).path).rstrip("/")
        if href_path == dav_root_path:
            return "/"
        if not href_path.startswith(f"{dav_root_path}/"):
            raise ProviderError(f"Unexpected Nextcloud WebDAV href: {href}")
        suffix = href_path[len(dav_root_path) :]
        return normalize_virtual_path(suffix)

    def _extract_checksum(self, checksums: str | None) -> str | None:
        if not checksums:
            return None
        for item in checksums.split():
            if ":" in item:
                return item.split(":", 1)[1]
        return checksums.strip() or None

    async def _find_existing_public_share(self, path: str) -> str | None:
        payload = await self._request_ocs_json(
            "GET",
            "/ocs/v2.php/apps/files_sharing/api/v1/shares",
            params={
                "path": path,
                "reshares": "false",
                "subfiles": "false",
            },
        )
        if isinstance(payload, dict):
            return self._extract_share_url(payload)
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                share_type = str(item.get("share_type") or item.get("shareType") or "")
                if share_type == "3":
                    url = self._extract_share_url(item)
                    if url:
                        return url
        return None

    def _extract_share_url(self, payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        url = payload.get("url")
        if url:
            return str(url)
        token = payload.get("token")
        if token:
            return f"{self._base_url}/s/{token}"
        return None

    async def _request_ocs_json(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
    ) -> Any:
        request_params = dict(params or {})
        request_params.setdefault("format", "json")
        headers = {
            "OCS-APIRequest": "true",
            "Accept": "application/json",
        }
        async with self._session.request(
            method,
            f"{self._base_url}{endpoint}",
            params=request_params,
            data=data,
            headers=headers,
        ) as response:
            if response.status not in {200, 201}:
                await self._raise_for_response(response)
            payload = await response.json(content_type=None)
        ocs = payload.get("ocs") if isinstance(payload, dict) else None
        if not isinstance(ocs, dict):
            raise ProviderError(f"Unexpected Nextcloud OCS payload: {payload!r}")
        meta = ocs.get("meta")
        if not isinstance(meta, dict):
            raise ProviderError(f"Unexpected Nextcloud OCS metadata: {payload!r}")
        status_code = int(meta.get("statuscode", 0))
        if status_code not in {100, 200}:
            message = str(meta.get("message") or "Nextcloud OCS request failed.")
            if status_code in {401, 403, 997, 998}:
                raise ProviderAuthenticationError(message)
            if status_code == 404:
                raise ResourceMissingError(message)
            if status_code in {405, 409}:
                raise ConflictError(message)
            raise ProviderError(message)
        return ocs.get("data")

    async def _request_empty(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        expected: set[int] | None = None,
    ) -> None:
        expected_codes = expected or {200, 201, 204}
        async with self._session.request(method, url, headers=headers) as response:
            if response.status not in expected_codes:
                await self._raise_for_response(response)

    async def _raise_for_response(self, response: aiohttp.ClientResponse) -> None:
        text = await response.text()
        if response.status in {401, 403}:
            raise ProviderAuthenticationError(text or "Provider authentication failed.")
        if response.status == 404:
            raise ResourceMissingError(text or "Remote resource not found.")
        if response.status in {405, 409, 412}:
            raise ConflictError(text or "Remote resource conflict.")
        raise ProviderError(f"Provider request failed with status {response.status}: {text}")
