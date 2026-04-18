import argparse
import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from .core.env_config import load_env_file
from .core.provider.yandex import YandexDiskProvider

logger = logging.getLogger(__name__)


def _normalize_remote_path(path: str, remote_root: str) -> str:
    local_root = os.getenv("LOCAL_PATH")
    if local_root:
        try:
            input_path = Path(path).expanduser().resolve(strict=False)
            local_root_path = Path(local_root).expanduser().resolve(strict=False)
            if input_path == local_root_path:
                path = ""
            else:
                relative_path = input_path.relative_to(local_root_path)
                path = relative_path.as_posix()
        except ValueError:
            pass

    if path.startswith("disk:"):
        path = path.replace("disk:", "", 1)
    if not path.startswith("/"):
        path = f"{remote_root.rstrip('/')}/{path}"
    normalized = "/" + path.strip("/")
    return normalized if normalized != "//" else "/"


def _safe_session_name(remote_path: str) -> str:
    digest = hashlib.sha256(remote_path.encode("utf-8")).hexdigest()[:16]
    basename = os.path.basename(remote_path.rstrip("/")) or "cloud-file"
    safe_basename = "".join(c if c.isalnum() or c in "._-" else "_" for c in basename)
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{digest}-{safe_basename}"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def _download_file(provider: YandexDiskProvider, remote_path: str, local_path: Path):
    local_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = local_path.with_suffix(local_path.suffix + ".part")
    try:
        with tmp_path.open("wb") as f:
            async for chunk in provider.get_file_content(remote_path):
                if chunk:
                    f.write(chunk)
        tmp_path.replace(local_path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _build_command(command: Optional[list[str]], local_path: Path) -> list[str]:
    if command == ["auto"]:
        command = None
    if not command:
        return _auto_command(local_path)
    if any("{file}" in part for part in command):
        return [part.replace("{file}", str(local_path)) for part in command]
    return [*command, str(local_path)]


def _first_available(commands: list[str]) -> Optional[str]:
    for command in commands:
        if shutil.which(command):
            return command
    return None


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


def _describe_file_type(local_path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(local_path))
    if not mime_type:
        return "unknown file"
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("text/"):
        return "text"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type == "application/pdf":
        return "pdf"
    return mime_type


def _open_and_wait(command: list[str], wait_for_enter: bool):
    print(f"[CloudBridge] opening: {' '.join(command)}", flush=True)
    process = subprocess.Popen(command)
    if wait_for_enter:
        input("[CloudBridge] Close the editor/viewer, then press Enter here to sync and clean up...")
        if process.poll() is None:
            process.terminate()
        return
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"Open command exited with status {return_code}")


async def open_cloud_file(
    remote_path: str,
    command: Optional[list[str]],
    wait_for_enter: bool,
    keep_unchanged: bool,
):
    token = os.getenv("YANDEX_TOKEN")
    if not token:
        raise RuntimeError("YANDEX_TOKEN is required")

    remote_root = os.getenv("YANDEX_PATH", "/")
    remote_path = _normalize_remote_path(remote_path, remote_root)
    sessions_root = Path(os.getenv("CLOUDBRIDGE_SESSION_DIR", "~/.cache/cloudbridge/sessions")).expanduser()
    session_dir = sessions_root / _safe_session_name(remote_path)
    local_path = session_dir / os.path.basename(remote_path.rstrip("/"))
    metadata_path = session_dir / "session.json"

    provider = YandexDiskProvider(token)
    try:
        print(f"[CloudBridge] downloading {remote_path}", flush=True)
        await _download_file(provider, remote_path, local_path)
        before_hash = _sha256_file(local_path)
        metadata = {
            "remote_path": remote_path,
            "local_path": str(local_path),
            "downloaded_at": datetime.now().isoformat(),
            "sha256_before": before_hash,
            "status": "opened",
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        open_command = _build_command(command, local_path)
        print(f"[CloudBridge] detected {_describe_file_type(local_path)}; using {' '.join(open_command)}", flush=True)
        _open_and_wait(open_command, wait_for_enter)

        if not local_path.exists():
            metadata["status"] = "local_file_missing"
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            raise RuntimeError(f"Temporary file disappeared: {local_path}")

        after_hash = _sha256_file(local_path)
        if after_hash == before_hash:
            metadata["status"] = "unchanged"
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            print("[CloudBridge] unchanged, no upload needed", flush=True)
            if not keep_unchanged:
                shutil.rmtree(session_dir)
                print("[CloudBridge] temporary copy removed", flush=True)
            return

        print(f"[CloudBridge] changed, uploading back to {remote_path}", flush=True)
        await provider.upload_file(str(local_path), remote_path)
        metadata["status"] = "uploaded"
        metadata["uploaded_at"] = datetime.now().isoformat()
        metadata["sha256_after"] = after_hash
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.rmtree(session_dir)
        print("[CloudBridge] uploaded successfully; temporary copy removed", flush=True)
    except Exception:
        print(f"[CloudBridge] session kept for recovery: {session_dir}", flush=True)
        raise
    finally:
        await provider.close()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Open a Yandex.Disk file in a temporary CloudBridge session and upload changes back."
    )
    parser.add_argument("remote_path", help="Remote path, e.g. /CloudBridgeTest/docs/123.txt or docs/123.txt")
    parser.add_argument(
        "--command",
        nargs=argparse.REMAINDER,
        help="Command to open the temp file. Use {file} placeholder or put it last automatically.",
    )
    parser.add_argument(
        "--wait-enter",
        action="store_true",
        help="Use with xdg-open: press Enter after closing the app, then CloudBridge syncs changes.",
    )
    parser.add_argument(
        "--keep-unchanged",
        action="store_true",
        help="Keep the temporary session even if the file was not changed.",
    )
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env_file()
    args = parse_args()
    wait_for_enter = args.wait_enter
    asyncio.run(open_cloud_file(args.remote_path, args.command, wait_for_enter, args.keep_unchanged))


if __name__ == "__main__":
    main()
