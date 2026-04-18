from __future__ import annotations

import asyncio
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from .config import AppConfig
from .filesystem import materialize_remote_placeholder_file, materialize_remote_placeholders, scan_local_subtree, scan_local_tree, stat_local_entry
from .models import EntryKind, IndexedEntry, JobOperation, SyncState
from .paths import basename, join_virtual_path, normalize_virtual_path, parent_path, virtual_to_local_path
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
            return NextcloudProvider(
                config.nextcloud_url or "",
                config.nextcloud_username or "",
                config.nextcloud_password or "",
            )
        raise ValueError(f"Unsupported provider: {config.provider_name}")

    async def close(self) -> None:
        await self._provider.close()
        await self._state.close()

    async def bootstrap(self) -> None:
        self._config.ensure_directories()
        await self._state.initialize()

    async def discover(self) -> list[IndexedEntry]:
        remote_entries = await self._provider.walk("/", concurrency=self._config.scan_concurrency)
        await asyncio.to_thread(materialize_remote_placeholders, self._config.sync_root, remote_entries)
        local_entries = await asyncio.to_thread(scan_local_tree, self._config.sync_root)
        await self._state.apply_remote_snapshot(self._provider.name, remote_entries, revision=uuid4().hex)
        await self._state.apply_local_snapshot(self._provider.name, local_entries, revision=uuid4().hex)
        return await self.list_directory("/")

    async def list_directory(self, path: str = "/") -> list[IndexedEntry]:
        return await self._state.list_directory(path)

    async def get_entry(self, path: str) -> IndexedEntry | None:
        return await self._state.get_entry(path)

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

    async def drain_sync_queue(self, limit: int | None = None) -> int:
        processed = 0
        while True:
            current = await self.run_sync_once(limit)
            if current == 0:
                return processed
            processed += current

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

    async def import_external_path(self, source: Path, destination_root: str | None = None) -> str:
        destination = await self.allocate_import_destination(source, destination_root=destination_root)
        await self.import_path(source, destination)
        return destination

    async def allocate_import_destination(self, source: Path, destination_root: str | None = None) -> str:
        candidate = self._build_import_candidate(source, destination_root=destination_root)
        return await self._dedupe_virtual_path(candidate)

    async def download(self, path: str) -> None:
        await self.queue_download(path)
        await self.run_sync_once(limit=1)

    async def dehydrate(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        remote_entry = await self._provider.stat(normalized)
        if remote_entry is None:
            raise FileNotFoundError(normalized)
        if remote_entry.kind is EntryKind.DIRECTORY:
            raise IsADirectoryError(normalized)
        await asyncio.to_thread(
            materialize_remote_placeholder_file,
            self._config.sync_root,
            remote_entry,
            overwrite_existing=True,
        )
        await self._state.upsert_remote_entries(self._provider.name, [remote_entry])
        await self._state.clear_local_prefix(self._provider.name, normalized)
        await self._state.resolve_entry_state(normalized)

    async def run_daemon(
        self,
        *,
        poll_interval: float = 2.0,
        refresh_interval: float = 30.0,
        once: bool = False,
    ) -> None:
        watcher = LocalWatcher(
            self._state,
            self._config.sync_root,
            self._provider.name,
            backend=self._config.watcher_backend,
        )
        try:
            await self.discover()
            await self._queue_startup_uploads()
            await watcher.start()
            print(f"daemon watcher={watcher.backend_name}")
            next_refresh_at = time.monotonic() + max(refresh_interval, poll_interval)

            while True:
                timeout = 0.0 if once else poll_interval
                changes = await watcher.poll(timeout=timeout)
                while await self.run_sync_once(limit=self._config.sync_concurrency):
                    continue

                if refresh_interval > 0 and time.monotonic() >= next_refresh_at:
                    await self.discover()
                    await self._queue_startup_uploads()
                    await watcher.seed()
                    next_refresh_at = time.monotonic() + refresh_interval

                if once:
                    return

                if not changes.is_empty:
                    continue
        finally:
            await watcher.close()

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

    async def _dedupe_virtual_path(self, path: str) -> str:
        normalized = normalize_virtual_path(path)
        if not await self._virtual_path_exists(normalized):
            return normalized

        name = basename(normalized)
        parent = parent_path(normalized)
        suffix = PurePosixPath(name).suffix
        stem = name[: -len(suffix)] if suffix else name

        counter = 2
        while True:
            candidate_name = f"{stem} ({counter}){suffix}"
            candidate = join_virtual_path(parent, candidate_name)
            if not await self._virtual_path_exists(candidate):
                return candidate
            counter += 1

    async def _virtual_path_exists(self, path: str) -> bool:
        normalized = normalize_virtual_path(path)
        if virtual_to_local_path(self._config.sync_root, normalized).exists():
            return True
        if await self._state.get_entry(normalized) is not None:
            return True
        return await self._provider.stat(normalized) is not None

    def _build_import_candidate(self, source: Path, destination_root: str | None = None) -> str:
        normalized_root = normalize_virtual_path(destination_root or self._config.import_root)
        if source.is_dir():
            return join_virtual_path(normalized_root, source.name)
        if self._config.import_layout == "by-parent":
            parent_name = source.parent.name.strip() or "root"
            return join_virtual_path(join_virtual_path(normalized_root, parent_name), source.name)
        if self._config.import_layout == "by-date":
            modified_at = datetime.fromtimestamp(source.stat().st_mtime, tz=UTC)
            year = f"{modified_at.year:04d}"
            month = f"{modified_at.month:02d}"
            return join_virtual_path(join_virtual_path(join_virtual_path(normalized_root, year), month), source.name)
        return join_virtual_path(normalized_root, source.name)
