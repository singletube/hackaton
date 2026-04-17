from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .models import EntryKind, LocalEntry, RemoteEntry
from .paths import basename, join_virtual_path, local_to_virtual_path, normalize_virtual_path, parent_path, virtual_to_local_path


PLACEHOLDER_MAGIC = b"CLOUDBRIDGE_PLACEHOLDER\n"
PLACEHOLDER_MAX_SIZE = 4096


def _from_timestamp(value: float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _build_placeholder_payload(entry: RemoteEntry) -> bytes:
    payload = {
        "path": entry.path,
        "size": entry.size,
        "checksum": entry.checksum,
        "modified_at": entry.modified_at.isoformat() if entry.modified_at else None,
    }
    return PLACEHOLDER_MAGIC + json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")


def is_placeholder_file(path: Path) -> bool:
    try:
        if not path.is_file():
            return False
        if path.stat().st_size > PLACEHOLDER_MAX_SIZE:
            return False
        with path.open("rb") as handle:
            return handle.read(len(PLACEHOLDER_MAGIC)) == PLACEHOLDER_MAGIC
    except OSError:
        return False


def _build_entry(virtual_path: str, entry: os.DirEntry[str]) -> LocalEntry | None:
    if entry.is_symlink():
        return None
    if not entry.is_dir(follow_symlinks=False) and is_placeholder_file(Path(entry.path)):
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
    if local_path.is_file() and is_placeholder_file(local_path):
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


def materialize_remote_placeholder_file(sync_root: Path, remote_entry: RemoteEntry, *, overwrite_existing: bool = False) -> None:
    if remote_entry.kind is not EntryKind.FILE:
        raise ValueError("materialize_remote_placeholder_file expects a file entry.")
    local_path = virtual_to_local_path(sync_root, remote_entry.path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    if local_path.exists() and not overwrite_existing and not is_placeholder_file(local_path):
        return
    local_path.write_bytes(_build_placeholder_payload(remote_entry))


def materialize_remote_placeholders(sync_root: Path, remote_entries: list[RemoteEntry]) -> None:
    sync_root.mkdir(parents=True, exist_ok=True)
    remote_directories = [entry.path for entry in remote_entries if entry.kind is EntryKind.DIRECTORY]
    materialize_remote_directories(sync_root, remote_directories)

    remote_files: dict[str, RemoteEntry] = {
        entry.path: entry for entry in remote_entries if entry.kind is EntryKind.FILE
    }
    for path, entry in remote_files.items():
        materialize_remote_placeholder_file(sync_root, entry)

    for current_path in sync_root.rglob("*"):
        if not current_path.is_file() or not is_placeholder_file(current_path):
            continue
        virtual_path = local_to_virtual_path(sync_root, current_path)
        if virtual_path in remote_files:
            continue
        current_path.unlink(missing_ok=True)
