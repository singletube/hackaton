from __future__ import annotations

import asyncio
from pathlib import Path

from .filesystem import scan_local_subtree
from .models import EntryKind, JobOperation, RemoteEntry, SyncJob, SyncState
from .paths import normalize_virtual_path, parent_path, virtual_to_local_path
from .providers.base import CloudProvider
from .state import StateDB


class SyncEngine:
    def __init__(self, state: StateDB, provider: CloudProvider, sync_root: Path, *, concurrency: int = 4) -> None:
        self._state = state
        self._provider = provider
        self._sync_root = sync_root
        self._concurrency = max(1, concurrency)

    async def run_once(self, limit: int | None = None) -> int:
        batch_size = limit or self._concurrency
        jobs = await self._state.claim_jobs(batch_size)
        if not jobs:
            return 0
        semaphore = asyncio.Semaphore(self._concurrency)

        async def run_job(job: SyncJob) -> None:
            async with semaphore:
                await self._process_job(job)

        async with asyncio.TaskGroup() as group:
            for job in jobs:
                group.create_task(run_job(job))
        return len(jobs)

    async def _process_job(self, job: SyncJob) -> None:
        await self._state.set_sync_state(job.path, SyncState.SYNCING)
        refresh_paths = [job.path]
        try:
            if job.operation is JobOperation.UPLOAD:
                await self._upload(job.path)
            elif job.operation is JobOperation.DOWNLOAD:
                await self._download(job.path)
            elif job.operation is JobOperation.MOVE_REMOTE:
                if not job.target_path:
                    raise ValueError("MOVE_REMOTE requires target_path.")
                await self._provider.move(job.path, job.target_path, overwrite=True)
                refresh_paths.append(job.target_path)
            elif job.operation is JobOperation.DELETE_REMOTE:
                await self._provider.delete(job.path)
                await self._state.clear_remote_prefix(self._provider.name, job.path)
            elif job.operation is JobOperation.DELETE_LOCAL:
                await asyncio.to_thread(self._delete_local, job.path)
                await self._state.clear_local_prefix(self._provider.name, job.path)
            for refresh_path in refresh_paths:
                await self._refresh_subtree(refresh_path)
            await self._state.complete_job(job.id)
            for refresh_path in refresh_paths:
                await self._state.resolve_entry_state(refresh_path)
        except Exception as error:
            await self._state.set_sync_state(job.path, SyncState.ERROR, str(error))
            await self._state.fail_job(job, str(error))

    async def _upload(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        local_root = virtual_to_local_path(self._sync_root, normalized)
        if not local_root.exists():
            raise FileNotFoundError(local_root)
        if local_root.is_dir():
            await self._provider.ensure_directory(normalized)
            entries = scan_local_subtree(self._sync_root, normalized)
            directories = [entry for entry in entries if entry.kind is EntryKind.DIRECTORY and entry.path != normalized]
            files = [entry for entry in entries if entry.kind is EntryKind.FILE]
            for directory in directories:
                await self._provider.ensure_directory(directory.path)
            for file_entry in files:
                await self._provider.upload_file(str(virtual_to_local_path(self._sync_root, file_entry.path)), file_entry.path, overwrite=True)
            return
        await self._provider.ensure_directory(parent_path(normalized))
        await self._provider.upload_file(str(local_root), normalized, overwrite=True)

    async def _download(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        remote_entry = await self._provider.stat(normalized)
        if remote_entry is None:
            raise FileNotFoundError(normalized)
        if remote_entry.kind is EntryKind.DIRECTORY:
            virtual_to_local_path(self._sync_root, normalized).mkdir(parents=True, exist_ok=True)
            descendants = await self._provider.walk(normalized)
            directories = [entry for entry in descendants if entry.kind is EntryKind.DIRECTORY]
            files = [entry for entry in descendants if entry.kind is EntryKind.FILE]
            for directory in directories:
                virtual_to_local_path(self._sync_root, directory.path).mkdir(parents=True, exist_ok=True)
            for file_entry in files:
                await self._provider.download_file(file_entry.path, str(virtual_to_local_path(self._sync_root, file_entry.path)))
            return
        await self._provider.download_file(normalized, str(virtual_to_local_path(self._sync_root, normalized)))

    async def _refresh_subtree(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        remote_entries = await self._collect_remote_entries(normalized)
        local_entries = await asyncio.to_thread(scan_local_subtree, self._sync_root, normalized)
        if remote_entries:
            await self._state.upsert_remote_entries(self._provider.name, remote_entries)
        else:
            await self._state.clear_remote_prefix(self._provider.name, normalized)
        if local_entries:
            await self._state.upsert_local_entries(self._provider.name, local_entries)
        else:
            await self._state.clear_local_prefix(self._provider.name, normalized)

    async def _collect_remote_entries(self, path: str) -> list[RemoteEntry]:
        root = await self._provider.stat(path)
        if root is None:
            return []
        if path == "/":
            return await self._provider.walk(path)
        if root.kind is EntryKind.FILE:
            return [root]
        descendants = await self._provider.walk(path)
        return [root, *descendants]

    def _delete_local(self, path: str) -> None:
        target = virtual_to_local_path(self._sync_root, path)
        if not target.exists():
            return
        if target.is_dir():
            for child in sorted(target.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink(missing_ok=True)
                elif child.is_dir():
                    child.rmdir()
            target.rmdir()
            return
        target.unlink(missing_ok=True)
