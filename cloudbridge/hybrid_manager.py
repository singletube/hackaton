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
        cloud_entries = await self._discover_cloud_entries(
            cloud_root=cloud_root,
            recursive=recursive,
            max_depth=max_depth,
        )
        local_entries = await asyncio.to_thread(self._scan_local_entries)

        cloud_count = await self._state_db.upsert_cloud_entries(cloud_entries)
        local_count = await self._state_db.upsert_local_entries(local_entries)
        if self._is_full_tree_snapshot(recursive=recursive, max_depth=max_depth):
            await self._state_db.reconcile_snapshot(
                cloud_paths={entry.path for entry in cloud_entries if entry.path},
                local_paths={entry.path for entry in local_entries if entry.path},
            )

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

    def _scan_local_entries(self) -> list[LocalEntry]:
        records: list[LocalEntry] = []
        for path in self._local_root.rglob("*"):
            rel_parts = path.relative_to(self._local_root).parts
            if any(part in self._IGNORED_PARTS for part in rel_parts):
                continue
            rel = "/".join(rel_parts)
            if not rel:
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
