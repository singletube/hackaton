import argparse
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from .cloud_open import _normalize_remote_path, show_error_dialog
from .keep_local import _local_target_for
from .core.env_config import load_env_file
from .core.ignore_list import add_ignored_path, remove_ignored_path
from .core.models import FileStatus
from .core.provider.yandex import YandexDiskProvider
from .core.xattr import set_placeholder_remote_path

logger = logging.getLogger(__name__)


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat()


async def restore_to_cloud(input_path: str):
    token = os.getenv("YANDEX_TOKEN")
    if not token:
        raise RuntimeError("YANDEX_TOKEN is required")

    remote_root = os.getenv("YANDEX_PATH", "/")
    remote_path = _normalize_remote_path(input_path, remote_root)
    local_path = _local_target_for(input_path, remote_path, remote_root)
    if not local_path.exists():
        raise FileNotFoundError(f"Local file not found: {local_path}")
    if local_path.is_dir():
        raise IsADirectoryError(str(local_path))

    provider = YandexDiskProvider(token)
    try:
        # Prevent watcher from uploading/truncating the file while this explicit action runs.
        add_ignored_path(remote_path)

        print(f"[CloudBridge] uploading local file to Yandex.Disk: {local_path} -> {remote_path}", flush=True)
        await provider.upload_file(str(local_path), remote_path)

        size = local_path.stat().st_size
        modified_at = _mtime_iso(local_path)

        print(f"[CloudBridge] replacing local file with placeholder: {local_path}", flush=True)
        with local_path.open("wb") as f:
            f.truncate(0)
        set_placeholder_remote_path(local_path, remote_path)

        try:
            from .core.database import StateDB

            db = StateDB(os.getenv("CLOUDBRIDGE_DB_PATH", "/tmp/state.db"))
            await db.initialize()
            await db.update_status(
                remote_path,
                FileStatus.OFFLINE,
                str(local_path),
                size=size,
                modified_at=modified_at,
            )
        except Exception as e:
            logger.warning("Could not update local StateDB for %s: %s", remote_path, e)

        remove_ignored_path(remote_path)
        print("[CloudBridge] done: file is back in cloud mode", flush=True)
    except Exception:
        print(
            "[CloudBridge] restore failed. The file is still in the ignore-list to prevent accidental watcher changes.",
            flush=True,
        )
        raise
    finally:
        await provider.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Upload a local-only file to Yandex.Disk and replace it with a placeholder.")
    parser.add_argument("path", help="Local file path or remote Yandex.Disk path")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env_file()
    args = parse_args()
    try:
        asyncio.run(restore_to_cloud(args.path))
    except Exception as exc:
        show_error_dialog(str(exc), title="CloudBridge restore cloud error")
        raise


if __name__ == "__main__":
    main()
