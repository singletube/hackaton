from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from .filesystem import scan_local_subtree, scan_local_tree
from .models import JobOperation, LocalEntry, SyncState
from .paths import local_to_virtual_path, normalize_virtual_path
from .state import StateDB

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover - exercised on environments without watchdog
    FileSystemEvent = object  # type: ignore[assignment]

    class FileSystemEventHandler:  # type: ignore[override]
        pass

    Observer = None  # type: ignore[assignment]


IGNORED_EVENT_TYPES = {"opened", "closed", "closed_no_write"}


@dataclass(slots=True, frozen=True)
class LocalChangeSet:
    uploaded_paths: tuple[str, ...]
    deleted_paths: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.uploaded_paths and not self.deleted_paths


class _WatchdogBridge(FileSystemEventHandler):
    def __init__(self, watcher: "LocalWatcher") -> None:
        self._watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        self._watcher.handle_filesystem_event(event)


class LocalWatcher:
    def __init__(self, state: StateDB, sync_root: Path, provider_name: str, *, backend: str = "auto") -> None:
        self._state = state
        self._sync_root = sync_root
        self._provider_name = provider_name
        self._snapshot: dict[str, LocalEntry] = {}
        self._requested_backend = backend.strip().lower() or "auto"
        self._backend = self._resolve_backend(self._requested_backend)
        self._pending_dirty: set[str] = set()
        self._pending_deleted: set[str] = set()
        self._pending_event = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._observer: Observer | None = None

    @property
    def backend_name(self) -> str:
        return self._backend

    async def start(self) -> None:
        await self.seed()
        if self._backend == "watchdog" and self._observer is None:
            self._start_watchdog()

    async def close(self) -> None:
        observer = self._observer
        if observer is None:
            return
        self._observer = None
        observer.stop()
        await asyncio.to_thread(observer.join, 5.0)
        self._pending_event.set()

    async def seed(self) -> None:
        entries = await asyncio.to_thread(scan_local_tree, self._sync_root)
        self._snapshot = {entry.path: entry for entry in entries}
        self._pending_dirty.clear()
        self._pending_deleted.clear()
        self._pending_event.clear()

    async def poll(self, timeout: float | None = None) -> LocalChangeSet:
        if self._backend == "watchdog":
            return await self._poll_pending(timeout)
        return await self._poll_tree(timeout)

    def handle_filesystem_event(self, event: FileSystemEvent) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._record_filesystem_event, event)

    def notify(self, path: str, *, deleted: bool = False) -> None:
        normalized = normalize_virtual_path(path)
        if normalized == "/":
            return
        if deleted:
            self._pending_deleted.add(normalized)
            self._pending_dirty.discard(normalized)
        else:
            self._pending_dirty.add(normalized)
            self._pending_deleted.discard(normalized)
        self._pending_event.set()

    async def _poll_tree(self, timeout: float | None) -> LocalChangeSet:
        current_entries = await asyncio.to_thread(scan_local_tree, self._sync_root)
        current_map = {entry.path: entry for entry in current_entries}

        changed_entries = [
            entry
            for path, entry in current_map.items()
            if self._entry_changed(self._snapshot.get(path), entry)
        ]
        deleted_paths = [path for path in self._snapshot if path not in current_map]

        self._snapshot = current_map
        changes = await self._persist_changes(changed_entries, deleted_paths)
        if changes.is_empty and timeout and timeout > 0:
            await asyncio.sleep(timeout)
        return changes

    async def _poll_pending(self, timeout: float | None) -> LocalChangeSet:
        if not self._pending_dirty and not self._pending_deleted and timeout and timeout > 0:
            try:
                await asyncio.wait_for(self._pending_event.wait(), timeout)
            except TimeoutError:
                return LocalChangeSet(uploaded_paths=(), deleted_paths=())

        candidate_paths = self._pending_dirty | self._pending_deleted
        self._pending_dirty.clear()
        self._pending_deleted.clear()
        self._pending_event.clear()
        if not candidate_paths:
            return LocalChangeSet(uploaded_paths=(), deleted_paths=())

        changed_entries: list[LocalEntry] = []
        deleted_paths: list[str] = []
        for root in self._collapse_paths(candidate_paths):
            previous_map = self._snapshot_subtree(root)
            current_entries = await asyncio.to_thread(scan_local_subtree, self._sync_root, root)
            current_map = {entry.path: entry for entry in current_entries}

            for path, entry in current_map.items():
                if self._entry_changed(previous_map.get(path), entry):
                    changed_entries.append(entry)
            for path in previous_map:
                if path not in current_map:
                    deleted_paths.append(path)

            self._replace_snapshot_subtree(root, current_map)

        return await self._persist_changes(changed_entries, deleted_paths)

    async def _persist_changes(self, changed_entries: list[LocalEntry], deleted_paths: list[str]) -> LocalChangeSet:
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

        return LocalChangeSet(uploaded_paths=tuple(upload_roots), deleted_paths=tuple(delete_roots))

    def _start_watchdog(self) -> None:
        if Observer is None:
            raise RuntimeError("watchdog backend requested but dependency is not installed.")
        self._loop = asyncio.get_running_loop()
        observer = Observer()
        observer.schedule(_WatchdogBridge(self), str(self._sync_root), recursive=True)
        observer.start()
        self._observer = observer

    def _record_filesystem_event(self, event: FileSystemEvent) -> None:
        event_type = getattr(event, "event_type", "")
        if event_type in IGNORED_EVENT_TYPES:
            return
        if getattr(event, "is_directory", False) and event_type == "modified":
            return

        src_path = self._to_virtual_path(getattr(event, "src_path", ""))
        if event_type == "moved":
            dest_path = self._to_virtual_path(getattr(event, "dest_path", ""))
            if src_path is not None:
                self.notify(src_path, deleted=True)
            if dest_path is not None:
                self.notify(dest_path)
            return

        if src_path is None:
            return
        self.notify(src_path, deleted=event_type == "deleted")

    def _to_virtual_path(self, path: str) -> str | None:
        if not path:
            return None
        try:
            normalized = local_to_virtual_path(self._sync_root, Path(path))
        except ValueError:
            return None
        return None if normalized == "/" else normalized

    def _snapshot_subtree(self, root: str) -> dict[str, LocalEntry]:
        normalized = normalize_virtual_path(root)
        prefix = f"{normalized}/"
        return {
            path: entry
            for path, entry in self._snapshot.items()
            if path == normalized or path.startswith(prefix)
        }

    def _replace_snapshot_subtree(self, root: str, current_map: dict[str, LocalEntry]) -> None:
        normalized = normalize_virtual_path(root)
        prefix = f"{normalized}/"
        stale_paths = [
            path
            for path in self._snapshot
            if path == normalized or path.startswith(prefix)
        ]
        for path in stale_paths:
            self._snapshot.pop(path, None)
        self._snapshot.update(current_map)

    @staticmethod
    def _resolve_backend(requested: str) -> str:
        if requested == "poll":
            return "poll"
        if requested == "watchdog":
            if Observer is None:
                raise RuntimeError("watchdog backend requested but dependency is not installed.")
            return "watchdog"
        if requested != "auto":
            raise ValueError(f"Unsupported watcher backend: {requested}")
        if Observer is not None and sys.platform.startswith("linux"):
            return "watchdog"
        return "poll"

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
            if path == "/":
                continue
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
