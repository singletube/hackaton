from __future__ import annotations

from pathlib import Path

import pytest

from cloudbridge.config import AppConfig
from cloudbridge.hybrid import HybridManager
from cloudbridge.models import EntryKind, RemoteEntry
from cloudbridge.paths import normalize_virtual_path, parent_path
from cloudbridge.providers.base import CloudProvider
from cloudbridge.state import StateDB


class MemoryProvider(CloudProvider):
    name = "memory"

    def __init__(self) -> None:
        self.entries: dict[str, RemoteEntry] = {}
        self.content: dict[str, bytes] = {}

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
        normalized = normalize_virtual_path(remote_path)
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        Path(local_path).write_bytes(self.content[normalized])

    async def delete(self, path: str, permanently: bool = True) -> None:
        normalized = normalize_virtual_path(path)
        self.entries.pop(normalized, None)
        self.content.pop(normalized, None)

    async def move(self, source_path: str, target_path: str, overwrite: bool = True) -> None:
        raise NotImplementedError

    async def publish(self, path: str) -> str:
        return f"https://example.test{normalize_virtual_path(path)}"


@pytest.mark.asyncio
async def test_queue_upload_and_download_roundtrip(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="memory",
        yandex_token="test-token",
        watcher_backend="poll",
    )
    config.ensure_directories()

    state = StateDB(config.database_path)
    await state.connect()
    provider = MemoryProvider()
    manager = HybridManager(config, state, provider)
    try:
        local_file = config.sync_root / "docs" / "report.txt"
        local_file.parent.mkdir(parents=True, exist_ok=True)
        local_file.write_text("payload", encoding="utf-8")

        await manager.queue_upload("/docs/report.txt")
        assert await manager.run_sync_once() == 1
        assert provider.content["/docs/report.txt"] == b"payload"

        local_file.unlink()
        await manager.queue_download("/docs/report.txt")
        assert await manager.run_sync_once() == 1
        assert local_file.read_text(encoding="utf-8") == "payload"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_run_sync_once_emits_job_events(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="memory",
        yandex_token="test-token",
        watcher_backend="poll",
    )
    config.ensure_directories()

    state = StateDB(config.database_path)
    await state.connect()
    provider = MemoryProvider()
    manager = HybridManager(config, state, provider)
    try:
        local_file = config.sync_root / "docs" / "report.txt"
        local_file.parent.mkdir(parents=True, exist_ok=True)
        local_file.write_text("payload", encoding="utf-8")

        await manager.queue_upload("/docs/report.txt")
        events = []

        assert await manager.run_sync_once(event_callback=events.append) == 1

        assert len(events) == 1
        assert events[0].succeeded is True
        assert events[0].job.operation is not None
        assert events[0].job.path == "/docs/report.txt"
    finally:
        await manager.close()
