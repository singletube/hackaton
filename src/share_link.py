import argparse
import asyncio
import logging
import os
from pathlib import Path
import shutil
import subprocess

from .cloud_open import _normalize_remote_path
from .core.env_config import load_env_file
from .core.provider.yandex import YandexDiskProvider

logger = logging.getLogger(__name__)


def _copy_to_clipboard(text: str):
    commands = [
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
        ["wl-copy"],
    ]
    for command in commands:
        if shutil.which(command[0]):
            process = subprocess.run(command, input=text, text=True, check=False)
            if process.returncode == 0:
                return command[0]
    return None


def _save_last_link(public_url: str) -> Path:
    cache_dir = Path(os.getenv("XDG_CACHE_HOME", "~/.cache")).expanduser() / "cloudbridge"
    cache_dir.mkdir(parents=True, exist_ok=True)
    link_path = cache_dir / "last_share_link.txt"
    link_path.write_text(public_url + "\n", encoding="utf-8")
    return link_path


def _notify(title: str, message: str):
    if not shutil.which("notify-send"):
        return
    subprocess.run(["notify-send", title, message], check=False)


async def create_share_link(input_path: str):
    token = os.getenv("YANDEX_TOKEN")
    if not token:
        raise RuntimeError("YANDEX_TOKEN is required")

    remote_root = os.getenv("YANDEX_PATH", "/")
    remote_path = _normalize_remote_path(input_path, remote_root)

    provider = YandexDiskProvider(token)
    try:
        print(f"[CloudBridge] creating read-only public link for {remote_path}", flush=True)
        public_url = await provider.publish_resource(remote_path)
        link_path = _save_last_link(public_url)
        clipboard_tool = _copy_to_clipboard(public_url)
        print("[CloudBridge] public link:", flush=True)
        print(public_url, flush=True)
        print(f"[CloudBridge] saved link to {link_path}", flush=True)
        if clipboard_tool:
            print(f"[CloudBridge] copied to clipboard via {clipboard_tool}", flush=True)
            _notify("CloudBridge", "Read-only link copied to clipboard")
        else:
            print(
                "[CloudBridge] clipboard tool not found. Copy the link above manually "
                "or install xclip, xsel, or wl-clipboard later.",
                flush=True,
            )
            _notify("CloudBridge", f"Link saved to {link_path}")
    finally:
        await provider.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Create a Yandex.Disk share link and copy it to clipboard.")
    parser.add_argument("path", help="Local placeholder path or remote Yandex.Disk path")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env_file()
    args = parse_args()
    asyncio.run(create_share_link(args.path))


if __name__ == "__main__":
    main()
