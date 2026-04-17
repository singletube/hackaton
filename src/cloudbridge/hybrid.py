from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from uuid import uuid4

from .config import AppConfig
from .filesystem import materialize_remote_directories, scan_local_subtree, scan_local_tree, stat_local_entry
from .models import EntryKind, IndexedEntry, JobOperation, SyncState
from .paths import normalize_virtual_path, virtual_to_local_path
from .providers import CloudProvider, NextcloudProvider, YandexDiskProvider
from .state import StateDB
from .sync import SyncEngine
from .watcher import LocalWatcher


class HybridManager:
    def __init__(self, config: AppConfig, state: StateDB, provider: CloudProvider) -> None:
        self._config = config
        self._state = state
        self._provider = provider
        self._sync = SyncEngine(state, provider, config.sync_root, concurrency=config.sync_concurrency)

    @classmethod
    async def from_config(cls, config: AppConfig) -> "HybridManager":
        config.ensure_directories()
        state = StateDB(config.database_path)
        await state.connect()
        provider = cls._build_provider(config)
        return cls(config, state, provider)

    @staticmethod
    def _build_provider(config: AppConfig) -> CloudProvider:
        if config.provider_name == "yandex":
            return YandexDiskProvider(config.yandex_token or "")
        if config.provider_name == "nextcloud":
            return NextcloudProvider()
        raise ValueError(f"Unsupported provider: {config.provider_name}")

    async def close(self) -> None:
        await self._provider.close()
        await self._state.close()

    async def bootstrap(self) -> None:
        self._config.ensure_directories()
        await self._state.initialize()

    async def discover(self) -> list[IndexedEntry]:
        remote_entries = await self._provider.walk("/", concurrency=self._config.scan_concurrency)
        remote_directories = [entry.path for entry in remote_entries if entry.kind is EntryKind.DIRECTORY]
        await asyncio.to_thread(materialize_remote_directories, self._config.sync_root, remote_directories)
        local_entries = await asyncio.to_thread(scan_local_tree, self._config.sync_root)
        await self._state.apply_remote_snapshot(self._provider.name, remote_entries, revision=uuid4().hex)
        await self._state.apply_local_snapshot(self._provider.name, local_entries, revision=uuid4().hex)
        return await self.list_directory("/")

    async def list_directory(self, path: str = "/") -> list[IndexedEntry]:
        return await self._state.list_directory(path)

    async def queue_upload(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        local_entry = await asyncio.to_thread(stat_local_entry, self._config.sync_root, normalized)
        if local_entry is None:
            raise FileNotFoundError(virtual_to_local_path(self._config.sync_root, normalized))
        await self._state.upsert_local_entries(self._provider.name, [local_entry])
        await self._state.enqueue_job(JobOperation.UPLOAD, normalized)
        await self._state.set_sync_state(normalized, SyncState.QUEUED)

    async def queue_download(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        remote_entry = await self._provider.stat(normalized)
        if remote_entry is None:
            raise FileNotFoundError(normalized)
        await self._state.upsert_remote_entries(self._provider.name, [remote_entry])
        await self._state.enqueue_job(JobOperation.DOWNLOAD, normalized)
        await self._state.set_sync_state(normalized, SyncState.QUEUED)

    async def queue_remote_delete(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        await self._state.enqueue_job(JobOperation.DELETE_REMOTE, normalized)
        await self._state.set_sync_state(normalized, SyncState.QUEUED)

    async def queue_local_delete(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        await self._state.enqueue_job(JobOperation.DELETE_LOCAL, normalized)
        await self._state.set_sync_state(normalized, SyncState.QUEUED)

    async def run_sync_once(self, limit: int | None = None) -> int:
        return await self._sync.run_once(limit)

    async def mkdir(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        await self._provider.ensure_directory(normalized)
        virtual_to_local_path(self._config.sync_root, normalized).mkdir(parents=True, exist_ok=True)
        remote_entry = await self._provider.stat(normalized)
        local_entry = await asyncio.to_thread(stat_local_entry, self._config.sync_root, normalized)
        if remote_entry:
            await self._state.upsert_remote_entries(self._provider.name, [remote_entry])
        if local_entry:
            await self._state.upsert_local_entries(self._provider.name, [local_entry])

    async def move(self, source: str, target: str) -> None:
        normalized_source = normalize_virtual_path(source)
        normalized_target = normalize_virtual_path(target)
        await self._provider.move(normalized_source, normalized_target)
        local_source = virtual_to_local_path(self._config.sync_root, normalized_source)
        local_target = virtual_to_local_path(self._config.sync_root, normalized_target)
        if local_source.exists():
            local_target.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.move, str(local_source), str(local_target))
        await self.discover()

    async def share(self, path: str) -> str:
        normalized = normalize_virtual_path(path)
        url = await self._provider.publish(normalized)
        remote_entry = await self._provider.stat(normalized)
        if remote_entry:
            await self._state.upsert_remote_entries(self._provider.name, [remote_entry])
        return url

    async def import_path(self, source: Path, destination: str) -> None:
        normalized = normalize_virtual_path(destination)
        local_destination = virtual_to_local_path(self._config.sync_root, normalized)
        local_destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            await asyncio.to_thread(shutil.copytree, source, local_destination, dirs_exist_ok=True)
        else:
            await asyncio.to_thread(shutil.copy2, source, local_destination)
        subtree = await asyncio.to_thread(scan_local_subtree, self._config.sync_root, normalized)
        await self._state.upsert_local_entries(self._provider.name, subtree)
        await self.queue_upload(normalized)
        await self.run_sync_once(limit=1)

    async def download(self, path: str) -> None:
        await self.queue_download(path)
        await self.run_sync_once(limit=1)

    async def run_daemon(
        self,
        *,
        poll_interval: float = 2.0,
        refresh_interval: float = 30.0,
        once: bool = False,
    ) -> None:
        watcher = LocalWatcher(self._state, self._config.sync_root, self._provider.name)
        await self.discover()
        await self._queue_startup_uploads()
        await watcher.seed()
        next_refresh_at = time.monotonic() + max(refresh_interval, poll_interval)

        while True:
            changes = await watcher.poll()
            while await self.run_sync_once(limit=self._config.sync_concurrency):
                continue

            if refresh_interval > 0 and time.monotonic() >= next_refresh_at:
                await self.discover()
                await self._queue_startup_uploads()
                await watcher.seed()
                next_refresh_at = time.monotonic() + refresh_interval

            if once:
                return

            await asyncio.sleep(0.25 if not changes.is_empty else poll_interval)

    async def _queue_startup_uploads(self) -> None:
        local_only_entries = await self._state.list_entries_by_states(SyncState.LOCAL_ONLY)
        upload_roots: list[str] = []
        for entry in sorted(local_only_entries, key=lambda item: item.path.count("/")):
            if any(entry.path == root or entry.path.startswith(f"{root}/") for root in upload_roots):
                continue
            upload_roots.append(entry.path)
        for path in upload_roots:
            await self._state.enqueue_job(JobOperation.UPLOAD, path)
            await self._state.set_sync_state(path, SyncState.QUEUED)
