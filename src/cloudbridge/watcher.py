from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable

from .filesystem import scan_local_tree
from .models import JobOperation, LocalEntry, SyncState
from .paths import normalize_virtual_path
from .state import StateDB


@dataclass(slots=True, frozen=True)
class LocalChangeSet:
    uploaded_paths: tuple[str, ...]
    deleted_paths: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.uploaded_paths and not self.deleted_paths


class LocalWatcher:
    def __init__(self, state: StateDB, sync_root, provider_name: str) -> None:
        self._state = state
        self._sync_root = sync_root
        self._provider_name = provider_name
        self._snapshot: dict[str, LocalEntry] = {}

    async def seed(self) -> None:
        entries = await asyncio.to_thread(scan_local_tree, self._sync_root)
        self._snapshot = {entry.path: entry for entry in entries}

    async def poll(self) -> LocalChangeSet:
        current_entries = await asyncio.to_thread(scan_local_tree, self._sync_root)
        current_map = {entry.path: entry for entry in current_entries}

        changed_entries = [
            entry
            for path, entry in current_map.items()
            if self._entry_changed(self._snapshot.get(path), entry)
        ]
        deleted_paths = [path for path in self._snapshot if path not in current_map]

        if changed_entries:
            await self._state.upsert_local_entries(self._provider_name, changed_entries)

        upload_roots = self._collapse_paths(entry.path for entry in changed_entries)
        delete_roots = self._collapse_paths(deleted_paths)

        for path in upload_roots:
            await self._state.enqueue_job(JobOperation.UPLOAD, path)
            await self._state.set_sync_state(path, SyncState.QUEUED)

        for path in delete_roots:
            indexed_entry = await self._state.get_entry(path)
            await self._state.clear_local_prefix(self._provider_name, path)
            if indexed_entry and indexed_entry.has_remote:
                await self._state.enqueue_job(JobOperation.DELETE_REMOTE, path)
                await self._state.set_sync_state(path, SyncState.QUEUED)

        self._snapshot = current_map
        return LocalChangeSet(uploaded_paths=tuple(upload_roots), deleted_paths=tuple(delete_roots))

    @staticmethod
    def _entry_changed(previous: LocalEntry | None, current: LocalEntry) -> bool:
        if previous is None:
            return True
        if previous.kind != current.kind:
            return True
        if current.kind.value == "directory":
            return False
        return previous.size != current.size or previous.modified_at != current.modified_at

    @staticmethod
    def _collapse_paths(paths: Iterable[str]) -> list[str]:
        collapsed: list[str] = []
        for path in sorted({normalize_virtual_path(item) for item in paths}, key=lambda value: value.count("/")):
            if any(LocalWatcher._is_parent(parent, path) for parent in collapsed):
                continue
            collapsed.append(path)
        return collapsed

    @staticmethod
    def _is_parent(parent: str, child: str) -> bool:
        if parent == child:
            return True
        parent_path = PurePosixPath(parent)
        child_path = PurePosixPath(child)
        return parent_path in child_path.parents
