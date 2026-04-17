from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .config import AppConfig
from .hybrid import HybridManager
from .models import EntryKind, IndexedEntry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cloudbridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")
    subparsers.add_parser("discover")

    list_parser = subparsers.add_parser("ls")
    list_parser.add_argument("path", nargs="?", default="/")

    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument("source")
    upload_parser.add_argument("destination")

    download_parser = subparsers.add_parser("download")
    download_parser.add_argument("path")

    mkdir_parser = subparsers.add_parser("mkdir")
    mkdir_parser.add_argument("path")

    move_parser = subparsers.add_parser("move")
    move_parser.add_argument("source")
    move_parser.add_argument("target")

    delete_parser = subparsers.add_parser("delete")
    delete_parser.add_argument("path")
    delete_parser.add_argument("--local", action="store_true", dest="delete_local")

    share_parser = subparsers.add_parser("share")
    share_parser.add_argument("path")

    queue_parser = subparsers.add_parser("queue")
    queue_subparsers = queue_parser.add_subparsers(dest="queue_command", required=True)
    queue_upload = queue_subparsers.add_parser("upload")
    queue_upload.add_argument("path")
    queue_download = queue_subparsers.add_parser("download")
    queue_download.add_argument("path")

    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--limit", type=int, default=None)

    return parser


def format_entry(entry: IndexedEntry) -> str:
    kind = "dir" if entry.kind is EntryKind.DIRECTORY else "file"
    size = "-" if entry.size is None else str(entry.size)
    return f"{kind:4} {entry.sync_state.value:12} {size:>10} {entry.path}"


async def run(args: argparse.Namespace) -> int:
    config = AppConfig.from_env()
    manager = await HybridManager.from_config(config)
    try:
        if args.command == "init":
            await manager.bootstrap()
            print(config.database_path)
            return 0
        if args.command == "discover":
            entries = await manager.discover()
            for entry in entries:
                print(format_entry(entry))
            return 0
        if args.command == "ls":
            entries = await manager.list_directory(args.path)
            for entry in entries:
                print(format_entry(entry))
            return 0
        if args.command == "upload":
            await manager.import_path(Path(args.source).expanduser().resolve(), args.destination)
            print(args.destination)
            return 0
        if args.command == "download":
            await manager.download(args.path)
            print(args.path)
            return 0
        if args.command == "mkdir":
            await manager.mkdir(args.path)
            print(args.path)
            return 0
        if args.command == "move":
            await manager.move(args.source, args.target)
            print(args.target)
            return 0
        if args.command == "delete":
            await manager.queue_remote_delete(args.path)
            await manager.run_sync_once(limit=1)
            if args.delete_local:
                await manager.queue_local_delete(args.path)
                await manager.run_sync_once(limit=1)
            print(args.path)
            return 0
        if args.command == "share":
            print(await manager.share(args.path))
            return 0
        if args.command == "queue":
            if args.queue_command == "upload":
                await manager.queue_upload(args.path)
            elif args.queue_command == "download":
                await manager.queue_download(args.path)
            return 0
        if args.command == "sync":
            print(await manager.run_sync_once(args.limit))
            return 0
        return 1
    finally:
        await manager.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(run(args))
