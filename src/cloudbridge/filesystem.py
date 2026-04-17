from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from .models import EntryKind, LocalEntry
from .paths import basename, join_virtual_path, normalize_virtual_path, parent_path, virtual_to_local_path


def _from_timestamp(value: float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _build_entry(virtual_path: str, entry: os.DirEntry[str]) -> LocalEntry | None:
    if entry.is_symlink():
        return None
    stat = entry.stat(follow_symlinks=False)
    kind = EntryKind.DIRECTORY if entry.is_dir(follow_symlinks=False) else EntryKind.FILE
    return LocalEntry(
        path=virtual_path,
        name=entry.name,
        parent_path=parent_path(virtual_path),
        kind=kind,
        size=None if kind is EntryKind.DIRECTORY else stat.st_size,
        modified_at=_from_timestamp(stat.st_mtime),
    )


def stat_local_entry(sync_root: Path, path: str) -> LocalEntry | None:
    local_path = virtual_to_local_path(sync_root, path)
    if not local_path.exists():
        return None
    stat = local_path.stat()
    kind = EntryKind.DIRECTORY if local_path.is_dir() else EntryKind.FILE
    normalized = normalize_virtual_path(path)
    return LocalEntry(
        path=normalized,
        name=basename(normalized),
        parent_path=parent_path(normalized),
        kind=kind,
        size=None if kind is EntryKind.DIRECTORY else stat.st_size,
        modified_at=_from_timestamp(stat.st_mtime),
    )


def scan_local_tree(sync_root: Path) -> list[LocalEntry]:
    sync_root.mkdir(parents=True, exist_ok=True)
    results: list[LocalEntry] = []
    stack: list[tuple[Path, str]] = [(sync_root, "/")]
    while stack:
        current_dir, current_virtual = stack.pop()
        with os.scandir(current_dir) as iterator:
            for item in iterator:
                item_virtual = join_virtual_path(current_virtual, item.name)
                entry = _build_entry(item_virtual, item)
                if entry is None:
                    continue
                results.append(entry)
                if entry.kind is EntryKind.DIRECTORY:
                    stack.append((Path(item.path), item_virtual))
    return results


def scan_local_subtree(sync_root: Path, root_path: str) -> list[LocalEntry]:
    normalized = normalize_virtual_path(root_path)
    local_root = virtual_to_local_path(sync_root, normalized)
    if not local_root.exists():
        return []
    root_entry = stat_local_entry(sync_root, normalized)
    if root_entry is None:
        return []
    if root_entry.kind is EntryKind.FILE:
        return [root_entry]
    results = [root_entry]
    stack: list[tuple[Path, str]] = [(local_root, normalized)]
    while stack:
        current_dir, current_virtual = stack.pop()
        with os.scandir(current_dir) as iterator:
            for item in iterator:
                item_virtual = join_virtual_path(current_virtual, item.name)
                entry = _build_entry(item_virtual, item)
                if entry is None:
                    continue
                results.append(entry)
                if entry.kind is EntryKind.DIRECTORY:
                    stack.append((Path(item.path), item_virtual))
    return results


def materialize_remote_directories(sync_root: Path, remote_paths: list[str]) -> None:
    sync_root.mkdir(parents=True, exist_ok=True)
    for path in sorted({normalize_virtual_path(item) for item in remote_paths}, key=lambda value: value.count("/")):
        if path == "/":
            continue
        virtual_to_local_path(sync_root, path).mkdir(parents=True, exist_ok=True)
