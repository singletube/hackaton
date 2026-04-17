from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Optional

from .config import Settings, load_settings
from .hybrid_manager import HybridManager
from .models import FileKind, FileStatus
from .provider import CloudProvider, ProviderError, YandexDiskProvider, NextCloudProvider
from .state_db import StateDB
from .watcher import LocalWatcher


def get_provider(settings: Settings) -> CloudProvider:
    if settings.provider_type == "nextcloud":
        if not settings.nextcloud_url or not settings.nextcloud_user or not settings.nextcloud_pass:
            raise ValueError("NextCloud requires NEXTCLOUD_URL, NEXTCLOUD_USER, and NEXTCLOUD_PASS")
        return NextCloudProvider(
            base_url=settings.nextcloud_url,
            username=settings.nextcloud_user,
            password=settings.nextcloud_pass,
        )
    else:
        if not settings.token:
            raise ValueError("Yandex Disk requires YA_DISK_TOKEN")
        return YandexDiskProvider(settings.token)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cloudbridge")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db-path", default=None, help="Path to SQLite state DB")
    common.add_argument("--local-root", default=None, help="Local directory for sync")
    common.add_argument("--cloud-root", default=None, help="Cloud root path (disk:/...)")
    common.add_argument("--token", default=None, help="Yandex Disk OAuth token")
    common.add_argument("--max-depth", type=int, default=None, help="Discovery depth")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "init-db", help="Create or migrate database schema", parents=[common]
    )

    discover = subparsers.add_parser(
        "discover",
        help="Fetch cloud metadata and merge with local tree",
        parents=[common],
    )
    discover.add_argument(
        "--non-recursive",
        action="store_true",
        help="Discover only one cloud folder level",
    )

    subparsers.add_parser(
        "watch",
        help="Watch local folder changes and queue sync statuses in DB",
        parents=[common],
    )
    mount = subparsers.add_parser(
        "mount",
        help="Mount read-only FUSE view backed by local+cloud metadata",
        parents=[common],
    )
    mount.add_argument("--mountpoint", required=True, help="FUSE mountpoint directory")
    mount.add_argument(
        "--allow-other",
        action="store_true",
        help="Allow other users to access mount (requires fuse config)",
    )

    share = subparsers.add_parser(
        "share",
        help="Generate a public share link for a cloud file",
        parents=[common],
    )
    share.add_argument("path", help="Cloud path to share (e.g. disk:/file.txt)")

    pin = subparsers.add_parser(
        "pin",
        help="Pin a file for offline access",
        parents=[common],
    )
    pin.add_argument("path", help="Relative path of the file to pin")

    unpin = subparsers.add_parser(
        "unpin",
        help="Unpin a file",
        parents=[common],
    )
    unpin.add_argument("path", help="Relative path of the file to unpin")

    return parser


def resolve_settings(args: argparse.Namespace) -> Settings:
    base = load_settings()
    db_path = Path(args.db_path).resolve() if args.db_path else base.db_path
    local_root = Path(args.local_root).resolve() if args.local_root else base.local_root
    cloud_root = args.cloud_root or base.cloud_root
    token = args.token if args.token is not None else base.token
    max_depth = args.max_depth if args.max_depth is not None else base.max_depth
    return Settings(
        provider_type=base.provider_type,
        token=token,
        nextcloud_url=base.nextcloud_url,
        nextcloud_user=base.nextcloud_user,
        nextcloud_pass=base.nextcloud_pass,
        db_path=db_path,
        local_root=local_root,
        cloud_root=cloud_root,
        max_depth=max_depth,
    )


async def run_init_db(settings: Settings) -> int:
    db = StateDB(settings.db_path)
    await db.connect()
    try:
        await db.init_schema()
    finally:
        await db.close()
    print(f"State DB initialized at: {settings.db_path}")
    return 0


async def run_discover(settings: Settings, *, recursive: bool) -> int:
    db = StateDB(settings.db_path)
    await db.connect()
    await db.init_schema()

    try:
        provider = get_provider(settings)
    except ValueError as e:
        print(e)
        return 2

    async with provider:
        manager = HybridManager(
            local_root=settings.local_root,
            provider=provider,
            state_db=db,
        )
        try:
            stats = await manager.discover(
                cloud_root=settings.cloud_root,
                recursive=recursive,
                max_depth=settings.max_depth,
            )
        except ProviderError as exc:
            print(f"Provider error: {exc}")
            await db.close()
            return 1

    await db.close()
    print(
        "Discovery completed:",
        f"cloud={stats.cloud_items}",
        f"local={stats.local_items}",
        f"merged={stats.merged_items}",
    )
    return 0


async def run_watch(settings: Settings) -> int:
    db = StateDB(settings.db_path)
    await db.connect()
    await db.init_schema()

    try:
        from .tray import start_tray_thread
        start_tray_thread()
    except ImportError:
        pass

    loop = asyncio.get_running_loop()
    watcher = LocalWatcher(settings.local_root)
    watcher.start(loop)

    print(f"Watching: {settings.local_root}")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            event = await watcher.next_event()
            path = Path(event.src_path)
            try:
                rel = path.resolve().relative_to(settings.local_root).as_posix()
            except ValueError:
                continue

            if not rel or rel.startswith(".cloudbridge"):
                continue

            exists = event.event_type != "deleted"
            status = FileStatus.QUEUED if exists else FileStatus.DELETED
            kind = FileKind.DIRECTORY.value if event.is_directory else FileKind.FILE.value

            await db.mark_local_event(
                rel,
                name=path.name,
                kind=kind,
                status=status,
                exists=exists,
            )
            print(f"{event.event_type:<8} {rel}")
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        await db.close()

    return 0


async def run_share(settings: Settings, path: str) -> int:
    try:
        provider = get_provider(settings)
    except ValueError as e:
        print(e)
        return 2

    async with provider:
        try:
            link = await provider.share_link(path)
            print(f"Shared link for '{path}':")
            print(link)
            # Try to copy to clipboard
            try:
                import subprocess
                # Try wl-copy first (Wayland), then xclip (X11)
                if not subprocess.run(["wl-copy"], input=link.encode(), capture_output=True).returncode:
                    print("(Copied to clipboard via Wayland)")
                elif not subprocess.run(["xclip", "-selection", "clipboard"], input=link.encode(), capture_output=True).returncode:
                    print("(Copied to clipboard via X11)")
            except FileNotFoundError:
                pass
        except ProviderError as exc:
            print(f"Failed to share link: {exc}")
            return 1
    return 0

async def run_pin(settings: Settings, path: str, pin: bool) -> int:
    db = StateDB(settings.db_path)
    await db.connect()
    try:
        await db.set_pinned(path, pin)
        print(f"{'Pinned' if pin else 'Unpinned'} '{path}'")
    except Exception as e:
        print(f"Error: {e}")
        return 1
    finally:
        await db.close()
    return 0

async def run_mount(settings: Settings, *, mountpoint: Path, allow_other: bool) -> int:
    try:
        from .fuse_fs import mount_cloudbridge
    except ModuleNotFoundError as exc:
        print(
            "FUSE dependencies are missing. Install pyfuse3 and pyfuse3-asyncio "
            "(or apt package python3-pyfuse3 on Ubuntu)."
        )
        print(f"Details: {exc}")
        return 2

    try:
        from .gvfs import add_bookmark, remove_bookmark
        add_bookmark(mountpoint, "CloudBridge")
    except ImportError:
        pass

    try:
        await mount_cloudbridge(
            mountpoint=mountpoint.resolve(),
            settings=settings,
            allow_other=allow_other,
        )
    finally:
        try:
            from .gvfs import remove_bookmark
            remove_bookmark(mountpoint)
        except ImportError:
            pass
    return 0


async def async_main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = resolve_settings(args)

    if args.command == "init-db":
        return await run_init_db(settings)
    if args.command == "discover":
        return await run_discover(settings, recursive=not args.non_recursive)
    if args.command == "watch":
        return await run_watch(settings)
    if args.command == "mount":
        return await run_mount(
            settings,
            mountpoint=Path(args.mountpoint),
            allow_other=bool(args.allow_other),
        )
    if args.command == "share":
        return await run_share(settings, args.path)
    if args.command == "pin":
        return await run_pin(settings, args.path, True)
    if args.command == "unpin":
        return await run_pin(settings, args.path, False)
    parser.error(f"Unknown command: {args.command}")
    return 2


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
