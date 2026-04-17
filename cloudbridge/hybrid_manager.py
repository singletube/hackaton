from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import CloudEntry, DiscoverStats, FileKind, LocalEntry
from .provider.base import CloudProvider
from .state_db import StateDB


class HybridManager:
    _IGNORED_PARTS = {
        ".cloudbridge",
        ".git",
        ".venv",
        "__pycache__",
        ".tmp",
        ".tmp_tests",
    }

    def __init__(
        self,
        *,
        local_root: Path,
        provider: CloudProvider,
        state_db: StateDB,
    ) -> None:
        self._local_root = local_root.resolve()
        self._provider = provider
        self._state_db = state_db

    async def discover(
        self,
        *,
        cloud_root: str = "disk:/",
        recursive: bool = True,
        max_depth: int = -1,
    ) -> DiscoverStats:
        known_placeholder_paths = await self._state_db.list_placeholder_paths()
        cloud_entries = await self._discover_cloud_entries(
            cloud_root=cloud_root,
            recursive=recursive,
            max_depth=max_depth,
        )
        local_entries = await asyncio.to_thread(
            self._scan_local_entries,
            known_placeholder_paths,
        )

        cloud_count = await self._state_db.upsert_cloud_entries(cloud_entries)
        local_count = await self._state_db.upsert_local_entries(local_entries)
        if self._is_full_tree_snapshot(recursive=recursive, max_depth=max_depth):
            await self._state_db.reconcile_snapshot(
                cloud_paths={entry.path for entry in cloud_entries if entry.path},
                local_paths={entry.path for entry in local_entries if entry.path},
            )

        await self._materialize_placeholders()

        merged_count = await self._state_db.count_present()

        return DiscoverStats(
            cloud_items=cloud_count,
            local_items=local_count,
            merged_items=merged_count,
        )

    async def _discover_cloud_entries(
        self,
        *,
        cloud_root: str,
        recursive: bool,
        max_depth: int,
    ) -> list[CloudEntry]:
        queue: deque[tuple[str, int]] = deque([(cloud_root, 0)])
        visited: set[str] = set()
        result: list[CloudEntry] = []

        while queue:
            current_path, depth = queue.popleft()
            if current_path in visited:
                continue
            visited.add(current_path)

            items = await self._provider.list_dir(current_path)
            for item in items:
                rel_path = self._cloud_to_rel_path(item.path, cloud_root)
                if rel_path is None:
                    continue
                result.append(
                    CloudEntry(
                        path=rel_path,
                        name=item.name,
                        kind=item.kind,
                        size=item.size,
                        etag=item.etag,
                        modified_at=item.modified_at,
                    )
                )

                if recursive and item.kind == FileKind.DIRECTORY and (
                    max_depth < 0 or depth < max_depth
                ):
                    queue.append((item.path, depth + 1))

        return result

    def _scan_local_entries(self, placeholder_paths: set[str]) -> list[LocalEntry]:
        records: list[LocalEntry] = []
        for path in self._local_root.rglob("*"):
            rel_parts = path.relative_to(self._local_root).parts
            if any(part in self._IGNORED_PARTS for part in rel_parts):
                continue
            rel = "/".join(rel_parts)
            if not rel:
                continue
            if self._is_placeholder_path(path, rel, placeholder_paths):
                continue
            if path.is_dir():
                kind = FileKind.DIRECTORY
                size = None
            else:
                kind = FileKind.FILE
                try:
                    size = path.stat().st_size
                except OSError:
                    size = None
            try:
                modified_at = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat()
            except OSError:
                modified_at = None
            records.append(
                LocalEntry(
                    path=rel,
                    name=path.name,
                    kind=kind,
                    size=size,
                    modified_at=modified_at,
                )
            )
        return records

    async def _materialize_placeholders(self) -> None:
        rows = await self._state_db.list_all(include_deleted=True)
        desired = {
            str(row["path"])
            for row in rows
            if str(row["path"])
            and bool(row["cloud_exists"])
            and not bool(row["local_exists"])
        }
        known = await self._state_db.list_placeholder_paths()

        for stale_path in sorted(known - desired, key=lambda value: value.count("/"), reverse=True):
            await asyncio.to_thread(self._remove_placeholder, stale_path)
            await self._state_db.set_presence(stale_path, placeholder=False)

        for row in rows:
            rel_path = str(row["path"] or "")
            if not rel_path or rel_path not in desired:
                continue
            await asyncio.to_thread(
                self._create_placeholder,
                rel_path,
                row["kind"] == FileKind.DIRECTORY.value,
            )
            await self._state_db.set_presence(rel_path, placeholder=True)

    def _create_placeholder(self, rel_path: str, is_dir: bool) -> None:
        local_path = (self._local_root / Path(rel_path)).resolve()
        if self._local_root not in local_path.parents and local_path != self._local_root:
            return
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if is_dir:
            local_path.mkdir(parents=True, exist_ok=True)
            return
        if not local_path.exists():
            local_path.touch()

    def _remove_placeholder(self, rel_path: str) -> None:
        local_path = (self._local_root / Path(rel_path)).resolve()
        if self._local_root not in local_path.parents and local_path != self._local_root:
            return
        if local_path.is_dir():
            try:
                next(local_path.iterdir())
                return
            except StopIteration:
                local_path.rmdir()
            except OSError:
                return
            return
        if local_path.exists() and local_path.is_file() and local_path.stat().st_size == 0:
            try:
                local_path.unlink()
            except OSError:
                return

    def _is_placeholder_path(
        self,
        path: Path,
        rel_path: str,
        placeholder_paths: set[str],
    ) -> bool:
        if rel_path not in placeholder_paths:
            return False
        if path.is_dir():
            return self._directory_contains_only_placeholders(path, placeholder_paths)
        try:
            return path.stat().st_size == 0
        except OSError:
            return False

    def _directory_contains_only_placeholders(
        self,
        path: Path,
        placeholder_paths: set[str],
    ) -> bool:
        try:
            children = list(path.iterdir())
        except OSError:
            return False
        for child in children:
            child_rel = child.relative_to(self._local_root).as_posix()
            if child_rel not in placeholder_paths:
                return False
            if child.is_dir():
                if not self._directory_contains_only_placeholders(child, placeholder_paths):
                    return False
                continue
            try:
                if child.stat().st_size != 0:
                    return False
            except OSError:
                return False
        return True

    @staticmethod
    def _cloud_to_rel_path(cloud_path: str, cloud_root: str) -> Optional[str]:
        path_ns, path_value = HybridManager._split_cloud_path(cloud_path)
        root_ns, root_value = HybridManager._split_cloud_path(cloud_root)

        if root_ns and path_ns and root_ns != path_ns:
            return None
        if root_ns and not path_ns:
            return None

        if not root_value:
            return path_value
        if path_value == root_value:
            return ""
        prefix = root_value + "/"
        if path_value.startswith(prefix):
            return path_value[len(prefix) :]
        return None

    @staticmethod
    def _split_cloud_path(value: str) -> tuple[Optional[str], str]:
        raw = str(value or "").strip()
        if raw.startswith("disk:/"):
            return "disk", raw[len("disk:/") :].strip("/")
        if raw == "disk:":
            return "disk", ""
        return None, raw.strip("/")

    @staticmethod
    def _is_full_tree_snapshot(*, recursive: bool, max_depth: int) -> bool:
        return recursive and max_depth < 0
