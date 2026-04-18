import argparse
import asyncio
import json
import logging
import mimetypes
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional

from .core.env_config import load_env_file
from .core.xattr import get_placeholder_remote_path, set_placeholder_remote_path

logger = logging.getLogger(__name__)
DESKTOP_ID = "cloudbridge-open-placeholder.desktop"


def _is_empty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size == 0
    except OSError:
        return False


def _fallback_remote_path(path: Path) -> str | None:
    local_root = os.getenv("LOCAL_PATH")
    remote_root = os.getenv("YANDEX_PATH", "/")
    if not local_root:
        return None

    try:
        relative = path.resolve(strict=False).relative_to(Path(local_root).expanduser().resolve(strict=False))
    except ValueError:
        return None
    remote_path = _normalize_remote_path(relative.as_posix(), remote_root)
    if not _db_has_offline_placeholder(remote_path):
        logger.info("No offline DB row for %s; treating empty file inside LOCAL_PATH as placeholder", remote_path)
    return remote_path


def _normalize_remote_path(path: str, remote_root: str) -> str:
    if path.startswith("disk:"):
        path = path.replace("disk:", "", 1)
    if not path.startswith("/"):
        path = f"{remote_root.rstrip('/')}/{path}"
    normalized = "/" + path.strip("/")
    return normalized if normalized != "//" else "/"


def _db_has_offline_placeholder(remote_path: str) -> bool:
    db_path = Path(os.getenv("CLOUDBRIDGE_DB_PATH", "/tmp/state.db"))
    if not db_path.exists():
        return False
    try:
        with sqlite3.connect(db_path) as db:
            row = db.execute("SELECT status FROM items WHERE path = ?", (remote_path,)).fetchone()
    except sqlite3.Error:
        return False
    return bool(row and row[0] == "offline")


def _placeholder_remote_path(path: Path) -> str | None:
    if not _is_empty_file(path):
        return None

    remote_path = get_placeholder_remote_path(path)
    if remote_path:
        return remote_path

    remote_path = _fallback_remote_path(path)
    if remote_path:
        set_placeholder_remote_path(path, remote_path)
    return remote_path


def _open_default(path: Path):
    mime_type = _query_mime_type(path)
    desktop_id = _previous_default_for(mime_type) if mime_type else None
    if desktop_id and desktop_id != DESKTOP_ID and shutil.which("gtk-launch"):
        logger.info("Opening non-placeholder with previous default %s", desktop_id)
        subprocess.Popen(["gtk-launch", desktop_id, str(path)])
        return

    command = _auto_command(path)
    logger.info("Opening non-placeholder with fallback command: %s", command)
    subprocess.Popen(command)


def _auto_command(local_path: Path) -> list[str]:
    mime_type, _ = mimetypes.guess_type(str(local_path))
    if mime_type and mime_type.startswith("image/"):
        viewer = os.getenv("CLOUDBRIDGE_IMAGE_VIEWER") or _first_available([
            "ristretto",
            "gpicview",
            "eog",
            "qimgv",
            "viewnior",
            "sxiv",
            "feh",
        ])
        if viewer:
            return [viewer, str(local_path)]

    if mime_type and mime_type.startswith("text/"):
        editor = os.getenv("CLOUDBRIDGE_TEXT_EDITOR") or _first_available([
            "mousepad",
            "xed",
            "gedit",
            "kate",
            "leafpad",
        ])
        if editor:
            return [editor, str(local_path)]

    return ["xdg-open", str(local_path)]


def _first_available(commands: list[str]) -> Optional[str]:
    for command in commands:
        if shutil.which(command):
            return command
    return None


def _query_mime_type(path: Path) -> str | None:
    process = subprocess.run(["xdg-mime", "query", "filetype", str(path)], text=True, capture_output=True, check=False)
    mime_type = process.stdout.strip()
    return mime_type or None


def _previous_default_for(mime_type: str | None) -> str | None:
    if not mime_type:
        return None
    defaults_file = Path("~/.config/cloudbridge/mime-defaults.json").expanduser()
    if not defaults_file.exists():
        return None
    try:
        defaults = json.loads(defaults_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return defaults.get(mime_type) or None


async def open_or_default(input_path: str):
    path = Path(input_path).expanduser()
    remote_path = _placeholder_remote_path(path)
    if remote_path:
        logger.info("Opening CloudBridge placeholder %s -> %s", path, remote_path)
        from .cloud_open import open_cloud_file, show_error_dialog

        try:
            await open_cloud_file(remote_path, command=None, wait_for_enter=False, keep_unchanged=False)
        except Exception as exc:
            show_error_dialog(str(exc))
            raise
        return

    _open_default(path)


def parse_args():
    parser = argparse.ArgumentParser(description="Open CloudBridge placeholders or fall back to the default app.")
    parser.add_argument("path")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env_file()
    args = parse_args()
    asyncio.run(open_or_default(args.path))


if __name__ == "__main__":
    main()
