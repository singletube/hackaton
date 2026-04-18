import argparse
import asyncio
import logging
import os
from pathlib import Path

from .cloud_open import _normalize_remote_path
from .core.env_config import load_env_file
from .core.ignore_list import add_ignored_path
from .core.provider.yandex import YandexDiskProvider

logger = logging.getLogger(__name__)


def _local_target_for(input_path: str, remote_path: str, remote_root: str) -> Path:
    local_root = os.getenv("LOCAL_PATH")
    if not local_root:
        raise RuntimeError("LOCAL_PATH is required to store files locally")

    input_local = Path(input_path).expanduser()
    local_root_path = Path(local_root).expanduser()
    try:
        input_local.resolve(strict=False).relative_to(local_root_path.resolve(strict=False))
        return input_local
    except ValueError:
        pass

    relative_remote = remote_path.strip("/")
    root = remote_root.strip("/")
    if root and relative_remote.startswith(root + "/"):
        relative_remote = relative_remote[len(root) + 1:]
    return local_root_path / relative_remote


async def _download_to_path(provider: YandexDiskProvider, remote_path: str, local_path: Path):
    local_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = local_path.with_name(f".{local_path.name}.cloudbridge-part")
    try:
        bytes_written = 0
        with tmp_path.open("wb") as f:
            async for chunk in provider.get_file_content(remote_path):
                if chunk:
                    bytes_written += len(chunk)
                    f.write(chunk)
        tmp_path.replace(local_path)
        print(f"[CloudBridge] stored locally: {local_path} ({bytes_written} bytes)", flush=True)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


async def keep_local(input_path: str):
    token = os.getenv("YANDEX_TOKEN")
    if not token:
        raise RuntimeError("YANDEX_TOKEN is required")

    remote_root = os.getenv("YANDEX_PATH", "/")
    remote_path = _normalize_remote_path(input_path, remote_root)
    local_path = _local_target_for(input_path, remote_path, remote_root)

    provider = YandexDiskProvider(token)
    try:
        print(f"[CloudBridge] adding to ignore-list: {remote_path}", flush=True)
        add_ignored_path(remote_path)

        print(f"[CloudBridge] downloading {remote_path} -> {local_path}", flush=True)
        await _download_to_path(provider, remote_path, local_path)

        print("[CloudBridge] done: file is stored locally and will not be uploaded back", flush=True)
        print("[CloudBridge] Yandex.Disk copy was not deleted", flush=True)
    except Exception:
        print(
            "[CloudBridge] ignore-list entry was kept to prevent accidental upload. "
            "Check the error above before editing this file.",
            flush=True,
        )
        raise
    finally:
        await provider.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Download a cloud placeholder locally and ignore future uploads.")
    parser.add_argument("path", help="Local placeholder path or remote Yandex.Disk path")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env_file()
    args = parse_args()
    asyncio.run(keep_local(args.path))


if __name__ == "__main__":
    main()
