from __future__ import annotations

from pathlib import Path

import pytest

from cloudbridge.cli import resolve_cli_path
from cloudbridge.cli import share_selected_path
from cloudbridge.config import AppConfig
from cloudbridge.hybrid import HybridManager
from cloudbridge.models import EntryKind, RemoteEntry
from cloudbridge.paths import normalize_virtual_path, parent_path
from cloudbridge.providers.base import CloudProvider
from cloudbridge.state import StateDB


def test_resolve_cli_path_maps_absolute_local_paths_inside_sync_root(tmp_path: Path) -> None:
    sync_root = tmp_path / "mirror"
    sync_root.mkdir()
    local_path = sync_root / "photos" / "turtle.jpg"
    local_path.parent.mkdir(parents=True)
    local_path.write_text("x", encoding="utf-8")

    assert resolve_cli_path(sync_root, str(local_path)) == "/photos/turtle.jpg"


def test_resolve_cli_path_keeps_external_absolute_paths_unchanged(tmp_path: Path) -> None:
    sync_root = tmp_path / "mirror"
    sync_root.mkdir()
    external_path = tmp_path / "Downloads" / "turtle.jpg"
    external_path.parent.mkdir(parents=True)
    external_path.write_text("x", encoding="utf-8")

    assert resolve_cli_path(sync_root, str(external_path)) == str(external_path)


class MemoryProvider(CloudProvider):
    name = "memory"

    def __init__(self) -> None:
        self.entries: dict[str, RemoteEntry] = {}
        self.content: dict[str, bytes] = {}
        self.published: list[str] = []

    async def list_directory(self, path: str) -> list[RemoteEntry]:
        normalized = normalize_virtual_path(path)
        return [entry for entry in self.entries.values() if entry.parent_path == normalized]

    async def stat(self, path: str) -> RemoteEntry | None:
        normalized = normalize_virtual_path(path)
        if normalized == "/":
            return RemoteEntry(path="/", name="", parent_path="/", kind=EntryKind.DIRECTORY)
        return self.entries.get(normalized)

    async def ensure_directory(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        if normalized == "/":
            return
        current = ""
        for segment in normalized.strip("/").split("/"):
            current = f"{current}/{segment}" if current else f"/{segment}"
            self.entries.setdefault(
                current,
                RemoteEntry(path=current, name=current.rsplit("/", 1)[-1], parent_path=parent_path(current), kind=EntryKind.DIRECTORY),
            )

    async def upload_file(self, local_path: str, remote_path: str, overwrite: bool = True) -> RemoteEntry:
        await self.ensure_directory(parent_path(remote_path))
        payload = Path(local_path).read_bytes()
        normalized = normalize_virtual_path(remote_path)
        entry = RemoteEntry(path=normalized, name=Path(local_path).name, parent_path=parent_path(normalized), kind=EntryKind.FILE, size=len(payload))
        self.entries[normalized] = entry
        self.content[normalized] = payload
        return entry

    async def download_file(self, remote_path: str, local_path: str) -> None:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        Path(local_path).write_bytes(self.content[normalize_virtual_path(remote_path)])

    async def delete(self, path: str, permanently: bool = True) -> None:
        normalized = normalize_virtual_path(path)
        self.entries.pop(normalized, None)
        self.content.pop(normalized, None)

    async def move(self, source_path: str, target_path: str, overwrite: bool = True) -> None:
        raise NotImplementedError

    async def publish(self, path: str) -> str:
        normalized = normalize_virtual_path(path)
        self.published.append(normalized)
        return f"https://example.test{normalized}"


@pytest.mark.asyncio
async def test_share_selected_uploads_local_only_file_inside_sync_root(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="memory",
        yandex_token="test-token",
        watcher_backend="poll",
    )
    config.ensure_directories()

    local_file = config.sync_root / "docs" / "report.txt"
    local_file.parent.mkdir(parents=True, exist_ok=True)
    local_file.write_text("payload", encoding="utf-8")

    state = StateDB(config.database_path)
    await state.connect()
    provider = MemoryProvider()
    manager = HybridManager(config, state, provider)
    try:
        url = await share_selected_path(manager, config.sync_root, str(local_file))

        assert url == "https://example.test/docs/report.txt"
        assert provider.content["/docs/report.txt"] == b"payload"
        assert provider.published == ["/docs/report.txt"]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_share_selected_imports_external_file_before_publish(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="memory",
        yandex_token="test-token",
        import_root="/incoming",
        watcher_backend="poll",
    )
    config.ensure_directories()

    external_file = tmp_path / "Downloads" / "photo.jpg"
    external_file.parent.mkdir(parents=True, exist_ok=True)
    external_file.write_bytes(b"jpeg")

    state = StateDB(config.database_path)
    await state.connect()
    provider = MemoryProvider()
    manager = HybridManager(config, state, provider)
    try:
        url = await share_selected_path(manager, config.sync_root, str(external_file))

        assert url == "https://example.test/incoming/photo.jpg"
        assert provider.content["/incoming/photo.jpg"] == b"jpeg"
        assert provider.published == ["/incoming/photo.jpg"]
    finally:
        await manager.close()
