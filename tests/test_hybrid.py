from __future__ import annotations

from pathlib import Path

import pytest

from cloudbridge.config import AppConfig
from cloudbridge.filesystem import is_placeholder_file
from cloudbridge.hybrid import HybridManager
from cloudbridge.models import EntryKind, RemoteEntry, SyncState
from cloudbridge.paths import normalize_virtual_path, parent_path
from cloudbridge.providers.base import CloudProvider
from cloudbridge.state import StateDB


class MemoryProvider(CloudProvider):
    name = "memory"

    def __init__(self) -> None:
        self._entries: dict[str, RemoteEntry] = {
            "/remote": RemoteEntry(path="/remote", name="remote", parent_path="/", kind=EntryKind.DIRECTORY),
            "/remote/file.txt": RemoteEntry(
                path="/remote/file.txt",
                name="file.txt",
                parent_path="/remote",
                kind=EntryKind.FILE,
                size=3,
            ),
        }
        self._content: dict[str, bytes] = {"/remote/file.txt": b"abc"}

    async def list_directory(self, path: str) -> list[RemoteEntry]:
        normalized = normalize_virtual_path(path)
        return [entry for entry in self._entries.values() if entry.parent_path == normalized]

    async def stat(self, path: str) -> RemoteEntry | None:
        normalized = normalize_virtual_path(path)
        if normalized == "/":
            return RemoteEntry(path="/", name="", parent_path="/", kind=EntryKind.DIRECTORY)
        return self._entries.get(normalized)

    async def ensure_directory(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        if normalized == "/":
            return
        current = ""
        for segment in normalized.strip("/").split("/"):
            current = f"{current}/{segment}" if current else f"/{segment}"
            self._entries.setdefault(
                current,
                RemoteEntry(path=current, name=current.rsplit("/", 1)[-1], parent_path=parent_path(current), kind=EntryKind.DIRECTORY),
            )

    async def upload_file(self, local_path: str, remote_path: str, overwrite: bool = True) -> RemoteEntry:
        await self.ensure_directory(parent_path(remote_path))
        data = Path(local_path).read_bytes()
        normalized = normalize_virtual_path(remote_path)
        entry = RemoteEntry(path=normalized, name=Path(local_path).name, parent_path=parent_path(normalized), kind=EntryKind.FILE, size=len(data))
        self._entries[normalized] = entry
        self._content[normalized] = data
        return entry

    async def download_file(self, remote_path: str, local_path: str) -> None:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        Path(local_path).write_bytes(self._content[normalize_virtual_path(remote_path)])

    async def delete(self, path: str, permanently: bool = True) -> None:
        normalized = normalize_virtual_path(path)
        prefixes = [item for item in self._entries if item == normalized or item.startswith(f"{normalized}/")]
        for prefix in prefixes:
            self._entries.pop(prefix, None)
            self._content.pop(prefix, None)

    async def move(self, source_path: str, target_path: str, overwrite: bool = True) -> None:
        normalized_source = normalize_virtual_path(source_path)
        normalized_target = normalize_virtual_path(target_path)
        entry = self._entries.pop(normalized_source)
        moved = RemoteEntry(
            path=normalized_target,
            name=normalized_target.rsplit("/", 1)[-1],
            parent_path=parent_path(normalized_target),
            kind=entry.kind,
            size=entry.size,
        )
        self._entries[normalized_target] = moved
        if normalized_source in self._content:
            self._content[normalized_target] = self._content.pop(normalized_source)

    async def publish(self, path: str) -> str:
        return f"https://example.test{normalize_virtual_path(path)}"


@pytest.mark.asyncio
async def test_discover_merges_remote_and_local_views(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="memory",
        yandex_token="test-token",
        watcher_backend="poll",
    )
    config.ensure_directories()
    (config.sync_root / "draft.txt").write_text("draft", encoding="utf-8")

    state = StateDB(config.database_path)
    await state.connect()
    manager = HybridManager(config, state, MemoryProvider())
    try:
        await manager.discover()
        root_entries = await manager.list_directory("/")
        by_path = {entry.path: entry for entry in root_entries}
        assert by_path["/remote"].sync_state is SyncState.SYNCED
        assert by_path["/draft.txt"].sync_state is SyncState.LOCAL_ONLY

        remote_entries = await manager.list_directory("/remote")
        assert remote_entries[0].path == "/remote/file.txt"
        assert remote_entries[0].sync_state is SyncState.PLACEHOLDER
        placeholder_path = config.sync_root / "remote" / "file.txt"
        assert placeholder_path.exists()
        assert is_placeholder_file(placeholder_path)
        assert placeholder_path.stat().st_size < 1024
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_daemon_once_uploads_startup_local_only_entries(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="memory",
        yandex_token="test-token",
        watcher_backend="poll",
    )
    config.ensure_directories()
    (config.sync_root / "startup.txt").write_text("daemon", encoding="utf-8")

    state = StateDB(config.database_path)
    await state.connect()
    provider = MemoryProvider()
    manager = HybridManager(config, state, provider)
    try:
        await manager.run_daemon(poll_interval=0.01, refresh_interval=0, once=True)

        entry = await state.get_entry("/startup.txt")
        assert entry is not None
        assert entry.sync_state is SyncState.SYNCED
        assert provider._content["/startup.txt"] == b"daemon"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_discover_cleans_stale_remote_placeholders(tmp_path: Path) -> None:
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
        await manager.discover()
        placeholder_path = config.sync_root / "remote" / "file.txt"
        assert placeholder_path.exists()
        assert is_placeholder_file(placeholder_path)

        provider._entries.pop("/remote/file.txt", None)
        provider._content.pop("/remote/file.txt", None)

        await manager.discover()
        assert not placeholder_path.exists()
        assert await state.get_entry("/remote/file.txt") is None
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_download_and_dehydrate_roundtrip(tmp_path: Path) -> None:
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
        await manager.discover()
        local_path = config.sync_root / "remote" / "file.txt"
        assert is_placeholder_file(local_path)

        await manager.download("/remote/file.txt")
        assert local_path.read_bytes() == b"abc"
        assert not is_placeholder_file(local_path)

        await manager.dehydrate("/remote/file.txt")
        entry = await state.get_entry("/remote/file.txt")
        assert entry is not None
        assert entry.sync_state is SyncState.PLACEHOLDER
        assert is_placeholder_file(local_path)
        assert local_path.stat().st_size < 1024
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_drain_sync_queue_processes_all_jobs(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="memory",
        yandex_token="test-token",
        watcher_backend="poll",
    )
    config.ensure_directories()
    (config.sync_root / "first.txt").write_text("first", encoding="utf-8")
    (config.sync_root / "second.txt").write_text("second", encoding="utf-8")

    state = StateDB(config.database_path)
    await state.connect()
    provider = MemoryProvider()
    manager = HybridManager(config, state, provider)
    try:
        await manager.queue_upload("/first.txt")
        await manager.queue_upload("/second.txt")

        processed = await manager.drain_sync_queue(limit=1)

        assert processed == 2
        assert provider._content["/first.txt"] == b"first"
        assert provider._content["/second.txt"] == b"second"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_allocate_import_destination_dedupes_existing_remote_name(tmp_path: Path) -> None:
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

    state = StateDB(config.database_path)
    await state.connect()
    provider = MemoryProvider()
    provider._entries["/incoming"] = RemoteEntry(
        path="/incoming",
        name="incoming",
        parent_path="/",
        kind=EntryKind.DIRECTORY,
    )
    provider._entries["/incoming/photo.jpg"] = RemoteEntry(
        path="/incoming/photo.jpg",
        name="photo.jpg",
        parent_path="/incoming",
        kind=EntryKind.FILE,
        size=3,
    )
    provider._content["/incoming/photo.jpg"] = b"old"

    manager = HybridManager(config, state, provider)
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"new")
    try:
        destination = await manager.allocate_import_destination(source)

        assert destination == "/incoming/photo (2).jpg"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_import_external_path_uses_deduped_destination(tmp_path: Path) -> None:
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

    state = StateDB(config.database_path)
    await state.connect()
    provider = MemoryProvider()
    provider._entries["/incoming"] = RemoteEntry(
        path="/incoming",
        name="incoming",
        parent_path="/",
        kind=EntryKind.DIRECTORY,
    )
    provider._entries["/incoming/photo.jpg"] = RemoteEntry(
        path="/incoming/photo.jpg",
        name="photo.jpg",
        parent_path="/incoming",
        kind=EntryKind.FILE,
        size=3,
    )
    provider._content["/incoming/photo.jpg"] = b"old"

    manager = HybridManager(config, state, provider)
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"new")
    try:
        destination = await manager.import_external_path(source)
        entry = await state.get_entry(destination)

        assert destination == "/incoming/photo (2).jpg"
        assert entry is not None
        assert provider._content["/incoming/photo.jpg"] == b"old"
        assert provider._content["/incoming/photo (2).jpg"] == b"new"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_allocate_import_destination_uses_parent_layout_for_files(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="memory",
        yandex_token="test-token",
        import_root="/incoming",
        import_layout="by-parent",
        watcher_backend="poll",
    )
    config.ensure_directories()

    state = StateDB(config.database_path)
    await state.connect()
    manager = HybridManager(config, state, MemoryProvider())
    source_dir = tmp_path / "Pictures"
    source_dir.mkdir()
    source = source_dir / "photo.jpg"
    source.write_bytes(b"new")
    try:
        destination = await manager.allocate_import_destination(source)

        assert destination == "/incoming/Pictures/photo.jpg"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_allocate_import_destination_uses_date_layout_for_files(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="memory",
        yandex_token="test-token",
        import_root="/incoming",
        import_layout="by-date",
        watcher_backend="poll",
    )
    config.ensure_directories()

    state = StateDB(config.database_path)
    await state.connect()
    manager = HybridManager(config, state, MemoryProvider())
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"new")
    try:
        destination = await manager.allocate_import_destination(source)

        assert destination.startswith("/incoming/")
        assert destination.endswith("/photo.jpg")
        assert destination.count("/") == 4
    finally:
        await manager.close()
