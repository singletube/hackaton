from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .config import AppConfig
from .filesystem import is_placeholder_file
from .hybrid import HybridManager
from .integration import (
    detect_file_manager,
    install_caja_integration,
    install_nautilus_integration,
    install_nemo_integration,
    install_systemd_user_service,
    install_thunar_integration,
)
from .models import EntryKind, IndexedEntry
from .paths import local_to_virtual_path, virtual_to_local_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cloudbridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")
    subparsers.add_parser("discover")

    list_parser = subparsers.add_parser("ls")
    list_parser.add_argument("path", nargs="?", default="/")

    info_parser = subparsers.add_parser("info")
    info_parser.add_argument("path")

    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument("source")
    upload_parser.add_argument("destination")

    upload_selected_parser = subparsers.add_parser("upload-selected")
    upload_selected_parser.add_argument("paths", nargs="+")

    download_parser = subparsers.add_parser("download")
    download_parser.add_argument("paths", nargs="+")

    dehydrate_parser = subparsers.add_parser("dehydrate")
    dehydrate_parser.add_argument("paths", nargs="+")

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
    queue_upload.add_argument("--sync", action="store_true")
    queue_upload.add_argument("paths", nargs="+")
    queue_download = queue_subparsers.add_parser("download")
    queue_download.add_argument("--sync", action="store_true")
    queue_download.add_argument("paths", nargs="+")

    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--limit", type=int, default=None)
    sync_parser.add_argument("--drain", action="store_true")

    daemon_parser = subparsers.add_parser("daemon")
    daemon_parser.add_argument("--poll-interval", type=float, default=2.0)
    daemon_parser.add_argument("--refresh-interval", type=float, default=30.0)
    daemon_parser.add_argument("--once", action="store_true")

    service_parser = subparsers.add_parser("install-service")
    service_parser.add_argument("--repo-root", default=str(Path.cwd()))
    service_parser.add_argument("--launcher-path")
    service_parser.add_argument("--unit-path")
    service_parser.add_argument("--service-name", default="cloudbridge")
    service_parser.add_argument("--uv-path")
    service_parser.add_argument("--launcher-command")
    service_parser.add_argument("--poll-interval", type=float, default=2.0)
    service_parser.add_argument("--refresh-interval", type=float, default=30.0)

    nautilus_parser = subparsers.add_parser("install-nautilus")
    nautilus_parser.add_argument("--repo-root", default=str(Path.cwd()))
    nautilus_parser.add_argument("--extension-dir")
    nautilus_parser.add_argument("--launcher-path")
    nautilus_parser.add_argument("--uv-path")
    nautilus_parser.add_argument("--launcher-command")

    thunar_parser = subparsers.add_parser("install-thunar")
    thunar_parser.add_argument("--repo-root", default=str(Path.cwd()))
    thunar_parser.add_argument("--config-path")
    thunar_parser.add_argument("--launcher-path")
    thunar_parser.add_argument("--uv-path")
    thunar_parser.add_argument("--launcher-command")

    nemo_parser = subparsers.add_parser("install-nemo")
    nemo_parser.add_argument("--repo-root", default=str(Path.cwd()))
    nemo_parser.add_argument("--actions-dir")
    nemo_parser.add_argument("--launcher-path")
    nemo_parser.add_argument("--uv-path")
    nemo_parser.add_argument("--launcher-command")

    caja_parser = subparsers.add_parser("install-caja")
    caja_parser.add_argument("--repo-root", default=str(Path.cwd()))
    caja_parser.add_argument("--actions-dir")
    caja_parser.add_argument("--launcher-path")
    caja_parser.add_argument("--uv-path")
    caja_parser.add_argument("--launcher-command")

    fm_parser = subparsers.add_parser("install-filemanager")
    fm_parser.add_argument("--manager", choices=("auto", "nautilus", "thunar", "nemo", "caja"), default="auto")
    fm_parser.add_argument("--repo-root", default=str(Path.cwd()))
    fm_parser.add_argument("--extension-dir")
    fm_parser.add_argument("--config-path")
    fm_parser.add_argument("--actions-dir")
    fm_parser.add_argument("--launcher-path")
    fm_parser.add_argument("--uv-path")
    fm_parser.add_argument("--launcher-command")

    return parser


def format_entry(entry: IndexedEntry) -> str:
    kind = "dir" if entry.kind is EntryKind.DIRECTORY else "file"
    size = "-" if entry.size is None else str(entry.size)
    return f"{kind:4} {entry.sync_state.value:12} {size:>10} {entry.path}"


def resolve_cli_path(sync_root: Path, raw_path: str) -> str:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        return raw_path
    try:
        return local_to_virtual_path(sync_root, candidate.resolve(strict=False))
    except ValueError:
        return raw_path


def resolve_local_source_path(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser().resolve()
    if not candidate.exists():
        raise FileNotFoundError(candidate)
    return candidate


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
            entries = await manager.list_directory(resolve_cli_path(config.sync_root, args.path))
            for entry in entries:
                print(format_entry(entry))
            return 0
        if args.command == "info":
            requested_path = resolve_cli_path(config.sync_root, args.path)
            entry = await manager.get_entry(requested_path)
            if entry is None:
                raise FileNotFoundError(requested_path)
            local_path = virtual_to_local_path(config.sync_root, requested_path)
            print(f"path={entry.path}")
            print(f"sync_state={entry.sync_state.value}")
            print(f"kind={entry.kind.value if entry.kind else 'unknown'}")
            print(f"has_remote={str(entry.has_remote).lower()}")
            print(f"has_local={str(entry.has_local).lower()}")
            print(f"remote_size={entry.remote_size if entry.remote_size is not None else ''}")
            print(f"local_size={entry.local_size if entry.local_size is not None else ''}")
            print(f"placeholder={str(is_placeholder_file(local_path)).lower()}")
            print(f"local_path={local_path}")
            return 0
        if args.command == "upload":
            await manager.import_path(Path(args.source).expanduser().resolve(), args.destination)
            print(args.destination)
            return 0
        if args.command == "upload-selected":
            for raw_path in args.paths:
                source = resolve_local_source_path(raw_path)
                resolved_path = resolve_cli_path(config.sync_root, str(source))
                if resolved_path != str(source):
                    await manager.queue_upload(resolved_path)
                    print(resolved_path)
                    continue
                destination = await manager.import_external_path(source)
                print(destination)
            return 0
        if args.command == "download":
            requested_paths = [resolve_cli_path(config.sync_root, path) for path in args.paths]
            for raw_path, requested_path in zip(args.paths, requested_paths, strict=True):
                try:
                    await manager.download(requested_path)
                except FileNotFoundError as error:
                    if Path(raw_path).expanduser().is_absolute() and requested_path == raw_path:
                        raise FileNotFoundError(
                            f"{raw_path} is not inside sync root {config.sync_root} and is not a cloud path. "
                            "Use a virtual path like /codex-test/turtle.jpeg or a local path inside the sync root."
                        ) from error
                    raise
                print(requested_path)
            return 0
        if args.command == "dehydrate":
            requested_paths = [resolve_cli_path(config.sync_root, path) for path in args.paths]
            for raw_path, requested_path in zip(args.paths, requested_paths, strict=True):
                try:
                    await manager.dehydrate(requested_path)
                except FileNotFoundError as error:
                    if Path(raw_path).expanduser().is_absolute() and requested_path == raw_path:
                        raise FileNotFoundError(
                            f"{raw_path} is not inside sync root {config.sync_root} and is not a cloud path. "
                            "Use a virtual path like /codex-test/turtle.jpeg or a local path inside the sync root."
                        ) from error
                    raise
                print(requested_path)
            return 0
        if args.command == "mkdir":
            await manager.mkdir(args.path)
            print(args.path)
            return 0
        if args.command == "move":
            resolved_source = resolve_cli_path(config.sync_root, args.source)
            resolved_target = resolve_cli_path(config.sync_root, args.target)
            await manager.move(resolved_source, resolved_target)
            print(resolved_target)
            return 0
        if args.command == "delete":
            requested_path = resolve_cli_path(config.sync_root, args.path)
            await manager.queue_remote_delete(requested_path)
            await manager.run_sync_once(limit=1)
            if args.delete_local:
                await manager.queue_local_delete(requested_path)
                await manager.run_sync_once(limit=1)
            print(requested_path)
            return 0
        if args.command == "share":
            print(await manager.share(resolve_cli_path(config.sync_root, args.path)))
            return 0
        if args.command == "queue":
            if args.queue_command == "upload":
                resolved_paths = [resolve_cli_path(config.sync_root, path) for path in args.paths]
                for path in resolved_paths:
                    await manager.queue_upload(path)
                if args.sync:
                    await manager.drain_sync_queue()
                for path in resolved_paths:
                    print(path)
            elif args.queue_command == "download":
                resolved_paths = [resolve_cli_path(config.sync_root, path) for path in args.paths]
                for path in resolved_paths:
                    await manager.queue_download(path)
                if args.sync:
                    await manager.drain_sync_queue()
                for path in resolved_paths:
                    print(path)
            return 0
        if args.command == "sync":
            if args.drain:
                print(await manager.drain_sync_queue(args.limit))
            else:
                print(await manager.run_sync_once(args.limit))
            return 0
        if args.command == "daemon":
            await manager.run_daemon(
                poll_interval=args.poll_interval,
                refresh_interval=args.refresh_interval,
                once=args.once,
            )
            return 0
        if args.command == "install-service":
            result = install_systemd_user_service(
                config,
                repo_root=Path(args.repo_root) if args.repo_root else None,
                uv_path=args.uv_path,
                launcher_command=args.launcher_command,
                launcher_path=Path(args.launcher_path).expanduser() if args.launcher_path else None,
                unit_path=Path(args.unit_path).expanduser() if args.unit_path else None,
                service_name=args.service_name,
                poll_interval=args.poll_interval,
                refresh_interval=args.refresh_interval,
            )
            print(f"service={result.service_name}")
            print(f"launcher={result.launcher_path}")
            print(f"unit={result.unit_path}")
            print("reload=systemctl --user daemon-reload")
            print(f"enable=systemctl --user enable --now {result.service_name}.service")
            return 0
        if args.command == "install-nautilus":
            result = install_nautilus_integration(
                config,
                repo_root=Path(args.repo_root),
                uv_path=args.uv_path,
                launcher_command=args.launcher_command,
                extension_dir=Path(args.extension_dir).expanduser() if args.extension_dir else None,
                launcher_path=Path(args.launcher_path).expanduser() if args.launcher_path else None,
            )
            print(f"launcher={result.launcher_path}")
            print(f"extension={result.extension_path}")
            print("restart_nautilus=nautilus -q")
            return 0
        if args.command == "install-thunar":
            result = install_thunar_integration(
                config,
                repo_root=Path(args.repo_root),
                uv_path=args.uv_path,
                launcher_command=args.launcher_command,
                config_path=Path(args.config_path).expanduser() if args.config_path else None,
                launcher_path=Path(args.launcher_path).expanduser() if args.launcher_path else None,
            )
            print(f"launcher={result.launcher_path}")
            print(f"config={result.config_path}")
            print("restart_thunar=thunar -q")
            return 0
        if args.command == "install-nemo":
            result = install_nemo_integration(
                config,
                repo_root=Path(args.repo_root),
                uv_path=args.uv_path,
                launcher_command=args.launcher_command,
                actions_dir=Path(args.actions_dir).expanduser() if args.actions_dir else None,
                launcher_path=Path(args.launcher_path).expanduser() if args.launcher_path else None,
            )
            print(f"launcher={result.launcher_path}")
            print(f"action={result.action_path}")
            print("restart_nemo=nemo -q")
            return 0
        if args.command == "install-caja":
            result = install_caja_integration(
                config,
                repo_root=Path(args.repo_root),
                uv_path=args.uv_path,
                launcher_command=args.launcher_command,
                actions_dir=Path(args.actions_dir).expanduser() if args.actions_dir else None,
                launcher_path=Path(args.launcher_path).expanduser() if args.launcher_path else None,
            )
            print(f"launcher={result.launcher_path}")
            print(f"action={result.action_path}")
            print("restart_caja=caja -q")
            return 0
        if args.command == "install-filemanager":
            manager_name = args.manager
            if manager_name == "auto":
                detected = detect_file_manager()
                if detected is None:
                    raise RuntimeError("Could not detect a supported file manager. Use --manager nautilus, thunar, nemo, or caja.")
                manager_name = detected
            if manager_name == "nautilus":
                result = install_nautilus_integration(
                    config,
                    repo_root=Path(args.repo_root),
                    uv_path=args.uv_path,
                    launcher_command=args.launcher_command,
                    extension_dir=Path(args.extension_dir).expanduser() if args.extension_dir else None,
                    launcher_path=Path(args.launcher_path).expanduser() if args.launcher_path else None,
                )
                print(f"manager=nautilus")
                print(f"launcher={result.launcher_path}")
                print(f"extension={result.extension_path}")
                print("restart=nautilus -q")
                return 0
            if manager_name == "thunar":
                result = install_thunar_integration(
                    config,
                    repo_root=Path(args.repo_root),
                    uv_path=args.uv_path,
                    launcher_command=args.launcher_command,
                    config_path=Path(args.config_path).expanduser() if args.config_path else None,
                    launcher_path=Path(args.launcher_path).expanduser() if args.launcher_path else None,
                )
                print("manager=thunar")
                print(f"launcher={result.launcher_path}")
                print(f"config={result.config_path}")
                print("restart=thunar -q")
                return 0
            if manager_name == "nemo":
                result = install_nemo_integration(
                    config,
                    repo_root=Path(args.repo_root),
                    uv_path=args.uv_path,
                    launcher_command=args.launcher_command,
                    actions_dir=Path(args.actions_dir).expanduser() if args.actions_dir else None,
                    launcher_path=Path(args.launcher_path).expanduser() if args.launcher_path else None,
                )
                print("manager=nemo")
                print(f"launcher={result.launcher_path}")
                print(f"action={result.action_path}")
                print("restart=nemo -q")
                return 0
            result = install_caja_integration(
                config,
                repo_root=Path(args.repo_root),
                uv_path=args.uv_path,
                launcher_command=args.launcher_command,
                actions_dir=Path(args.actions_dir).expanduser() if args.actions_dir else None,
                launcher_path=Path(args.launcher_path).expanduser() if args.launcher_path else None,
            )
            print("manager=caja")
            print(f"launcher={result.launcher_path}")
            print(f"action={result.action_path}")
            print("restart=caja -q")
            return 0
        return 1
    finally:
        await manager.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(run(args))
