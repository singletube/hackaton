import json
import os
from pathlib import Path


def ignore_file_path() -> Path:
    return Path(os.getenv("CLOUDBRIDGE_IGNORE_FILE", "~/.config/cloudbridge/ignored.json")).expanduser()


def _normalize_remote_path(path: str) -> str:
    if path.startswith("disk:"):
        path = path.replace("disk:", "", 1)
    normalized = "/" + path.strip("/")
    return normalized if normalized != "//" else "/"


def load_ignored_paths() -> set[str]:
    path = ignore_file_path()
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return {_normalize_remote_path(item) for item in data.get("remote_paths", [])}


def save_ignored_paths(paths: set[str]):
    path = ignore_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"remote_paths": sorted({_normalize_remote_path(item) for item in paths})}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_ignored_path(remote_path: str):
    paths = load_ignored_paths()
    paths.add(_normalize_remote_path(remote_path))
    save_ignored_paths(paths)


def remove_ignored_path(remote_path: str):
    paths = load_ignored_paths()
    paths.discard(_normalize_remote_path(remote_path))
    save_ignored_paths(paths)


def is_ignored(remote_path: str) -> bool:
    normalized = _normalize_remote_path(remote_path)
    for ignored in load_ignored_paths():
        if normalized == ignored or normalized.startswith(ignored.rstrip("/") + "/"):
            return True
    return False
