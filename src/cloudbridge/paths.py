from __future__ import annotations

from pathlib import Path, PurePosixPath


def normalize_virtual_path(path: str | PurePosixPath) -> str:
    raw = str(path).replace("\\", "/").strip() or "/"
    pure = PurePosixPath(raw)
    parts: list[str] = []
    for part in pure.parts:
        if part in {"", "/", "."}:
            continue
        if part == "..":
            raise ValueError(f"Path traversal is not allowed: {path!r}")
        parts.append(part)
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def basename(path: str) -> str:
    normalized = normalize_virtual_path(path)
    if normalized == "/":
        return ""
    return PurePosixPath(normalized).name


def parent_path(path: str) -> str:
    normalized = normalize_virtual_path(path)
    if normalized == "/":
        return "/"
    parent = PurePosixPath(normalized).parent.as_posix()
    return normalize_virtual_path(parent)


def join_virtual_path(parent: str, name: str) -> str:
    base = PurePosixPath(normalize_virtual_path(parent))
    return normalize_virtual_path(base / name)


def virtual_to_local_path(sync_root: Path, path: str) -> Path:
    normalized = normalize_virtual_path(path)
    if normalized == "/":
        return sync_root
    return sync_root.joinpath(*PurePosixPath(normalized).parts[1:])


def local_to_virtual_path(sync_root: Path, path: Path) -> str:
    relative = path.resolve().relative_to(sync_root.resolve())
    return normalize_virtual_path(relative.as_posix())

