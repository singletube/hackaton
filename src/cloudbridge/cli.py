from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from pathlib import Path
import shutil

from .clipboard import copy_text_to_clipboard
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
from .notifications import send_desktop_notification
from .paths import local_to_virtual_path, virtual_to_local_path
from .providers import NextcloudProvider, YandexDiskProvider
from .setup import run_nextcloud_login_flow, run_yandex_device_login_flow


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
    share_parser.add_argument("--copy", action="store_true")

    share_selected_parser = subparsers.add_parser("share-selected")
    share_selected_parser.add_argument("--copy", action="store_true")
    share_selected_parser.add_argument("paths", nargs="+")

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

    gui_parser = subparsers.add_parser("gui")
    gui_parser.add_argument("--manager", choices=("auto", "nautilus", "thunar", "nemo", "caja"), default="auto")

    setup_yandex_parser = subparsers.add_parser("setup-yandex")
    setup_yandex_parser.add_argument("--client-id")
    setup_yandex_parser.add_argument("--client-secret")
    setup_yandex_parser.add_argument(
        "--scope",
        default="cloud_api:disk.read cloud_api:disk.write cloud_api:disk.info",
    )
    setup_yandex_parser.add_argument("--timeout", type=float, default=900.0)
    setup_yandex_parser.add_argument("--no-browser", action="store_true")

    setup_nextcloud_parser = subparsers.add_parser("setup-nextcloud")
    setup_nextcloud_parser.add_argument("--server", required=True)
    setup_nextcloud_parser.add_argument("--timeout", type=float, default=600.0)
    setup_nextcloud_parser.add_argument("--poll-interval", type=float, default=1.0)
    setup_nextcloud_parser.add_argument("--no-browser", action="store_true")

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
    caja_parser.add_argument("--extension-dir")
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

    desktop_parser = subparsers.add_parser("desktop-setup")
    desktop_parser.add_argument("--manager", choices=("auto", "nautilus", "thunar", "nemo", "caja"), default="auto")
    desktop_parser.add_argument("--skip-filemanager", action="store_true")
    desktop_parser.add_argument("--skip-service", action="store_true")
    desktop_parser.add_argument("--service-name", default="cloudbridge")
    desktop_parser.add_argument("--poll-interval", type=float, default=2.0)
    desktop_parser.add_argument("--refresh-interval", type=float, default=30.0)
    desktop_parser.add_argument("--launcher-command")

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


async def share_selected_path(manager: HybridManager, sync_root: Path, raw_path: str) -> str:
    resolved_path = resolve_cli_path(sync_root, raw_path)
    candidate = Path(raw_path).expanduser()
    local_exists = candidate.is_absolute() and candidate.exists()

    if local_exists and resolved_path == raw_path:
        source = resolve_local_source_path(raw_path)
        destination = await manager.import_external_path(source)
        return await manager.share(destination)

    if local_exists:
        entry = await manager.get_entry(resolved_path)
        if entry is None or not entry.has_remote:
            await manager.queue_upload(resolved_path)
            await manager.run_sync_once(limit=1)
    return await manager.share(resolved_path)


async def run(args: argparse.Namespace) -> int:
    config = AppConfig.from_env()
    if args.command == "gui":
        from .gui import launch_gui

        return launch_gui(config, manager_name=args.manager)

    if args.command == "setup-yandex":
        client_id = (args.client_id or config.yandex_client_id or "").strip()
        client_secret = (args.client_secret or config.yandex_client_secret or "").strip()
        if not client_id or not client_secret:
            raise ValueError("Yandex device login requires --client-id and --client-secret, or saved YANDEX_CLIENT_ID / YANDEX_CLIENT_SECRET.")

        def handle_yandex_ready(prompt) -> None:
            print("action=Open the verification URL and enter the user_code shown below. The code is not sent by Yandex in email or SMS.")
            print(f"verification_url={prompt.verification_url}")
            print(f"user_code={prompt.user_code}")
            print(f"browser_opened={str(prompt.browser_opened).lower()}")

        result = await run_yandex_device_login_flow(
            client_id,
            client_secret,
            scope=args.scope,
            open_browser=not args.no_browser,
            timeout=args.timeout,
            on_ready=handle_yandex_ready,
        )

        provider = YandexDiskProvider(result.access_token)
        try:
            if await provider.stat("/") is None:
                raise RuntimeError("Yandex login completed, but the Disk root is not accessible.")
        finally:
            await provider.close()

        updated_config = replace(
            config,
            provider_name="yandex",
            yandex_token=result.access_token,
            yandex_client_id=client_id,
            yandex_client_secret=client_secret,
        )
        updated_config.write_persisted_settings()
        print(f"config={updated_config.resolved_config_path}")
        return 0

    if args.command == "setup-nextcloud":
        def handle_nextcloud_ready(prompt) -> None:
            print("action=Open the login_url in a browser and complete the Nextcloud approval flow there.")
            print(f"login_url={prompt.login_url}")
            print(f"browser_opened={str(prompt.browser_opened).lower()}")

        result = await run_nextcloud_login_flow(
            args.server,
            open_browser=not args.no_browser,
            timeout=args.timeout,
            poll_interval=args.poll_interval,
            on_ready=handle_nextcloud_ready,
        )
        provider = NextcloudProvider(result.server_url, result.login_name, result.app_password)
        try:
            if await provider.stat("/") is None:
                raise RuntimeError("Nextcloud login completed, but the WebDAV root is not accessible.")
        finally:
            await provider.close()

        updated_config = replace(
            config,
            provider_name="nextcloud",
            nextcloud_url=result.server_url,
            nextcloud_username=result.login_name,
            nextcloud_password=result.app_password,
            yandex_token=None,
        )
        updated_config.write_persisted_settings()
        print(f"server={result.server_url}")
        print(f"username={result.login_name}")
        print(f"config={updated_config.resolved_config_path}")
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
        print("actions=" + ",".join(str(path) for path in result.action_paths))
        print("restart_nemo=nemo -q")
        return 0
    if args.command == "install-caja":
        result = install_caja_integration(
            config,
            repo_root=Path(args.repo_root),
            uv_path=args.uv_path,
            launcher_command=args.launcher_command,
            extension_dir=Path(args.extension_dir).expanduser() if args.extension_dir else None,
            actions_dir=Path(args.actions_dir).expanduser() if args.actions_dir else None,
            launcher_path=Path(args.launcher_path).expanduser() if args.launcher_path else None,
        )
        print(f"launcher={result.launcher_path}")
        print(f"extension={result.extension_path}")
        print("actions=" + ",".join(str(path) for path in result.action_paths))
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
            print("manager=nautilus")
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
            print("actions=" + ",".join(str(path) for path in result.action_paths))
            print("restart=nemo -q")
            return 0
        result = install_caja_integration(
            config,
            repo_root=Path(args.repo_root),
            uv_path=args.uv_path,
            launcher_command=args.launcher_command,
            extension_dir=Path(args.extension_dir).expanduser() if args.extension_dir else None,
            actions_dir=Path(args.actions_dir).expanduser() if args.actions_dir else None,
            launcher_path=Path(args.launcher_path).expanduser() if args.launcher_path else None,
        )
        print("manager=caja")
        print(f"launcher={result.launcher_path}")
        print(f"extension={result.extension_path}")
        print("actions=" + ",".join(str(path) for path in result.action_paths))
        print("restart=caja -q")
        return 0

    if args.command == "desktop-setup":
        launcher_command = args.launcher_command or _default_installed_launcher_command()
        manager = await HybridManager.from_config(config)
        try:
            await manager.bootstrap()
        finally:
            await manager.close()
        print(f"database={config.database_path}")
        print(f"config={config.resolved_config_path}")

        if not args.skip_filemanager:
            manager_name = args.manager
            if manager_name == "auto":
                detected = detect_file_manager()
                if detected is None:
                    raise RuntimeError("Could not detect a supported file manager. Use --manager nautilus, thunar, nemo, or caja.")
                manager_name = detected
            if manager_name == "nautilus":
                result = install_nautilus_integration(
                    config,
                    repo_root=None,
                    launcher_command=launcher_command,
                )
                print("manager=nautilus")
                print(f"launcher={result.launcher_path}")
                print(f"extension={result.extension_path}")
                print("restart=nautilus -q")
            elif manager_name == "thunar":
                result = install_thunar_integration(
                    config,
                    repo_root=None,
                    launcher_command=launcher_command,
                )
                print("manager=thunar")
                print(f"launcher={result.launcher_path}")
                print(f"config_path={result.config_path}")
                print("restart=thunar -q")
            elif manager_name == "nemo":
                result = install_nemo_integration(
                    config,
                    repo_root=None,
                    launcher_command=launcher_command,
                )
                print("manager=nemo")
                print(f"launcher={result.launcher_path}")
                print("actions=" + ",".join(str(path) for path in result.action_paths))
                print("restart=nemo -q")
            else:
                result = install_caja_integration(
                    config,
                    repo_root=None,
                    launcher_command=launcher_command,
                )
                print("manager=caja")
                print(f"launcher={result.launcher_path}")
                print(f"extension={result.extension_path}")
                print("actions=" + ",".join(str(path) for path in result.action_paths))
                print("restart=caja -q")

        if not args.skip_service:
            result = install_systemd_user_service(
                config,
                repo_root=None,
                launcher_command=launcher_command,
                service_name=args.service_name,
                poll_interval=args.poll_interval,
                refresh_interval=args.refresh_interval,
            )
            print(f"service={result.service_name}")
            print(f"service_launcher={result.launcher_path}")
            print(f"unit={result.unit_path}")
            print("reload=systemctl --user daemon-reload")
            print(f"enable=systemctl --user enable --now {result.service_name}.service")
        return 0

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
            url = await manager.share(resolve_cli_path(config.sync_root, args.path))
            print(url)
            if args.copy:
                copied = copy_text_to_clipboard(url)
                print(f"clipboard={str(copied).lower()}")
                if copied:
                    send_desktop_notification("CloudBridge", "Public link copied to clipboard.")
            return 0
        if args.command == "share-selected":
            urls: list[str] = []
            for raw_path in args.paths:
                url = await share_selected_path(manager, config.sync_root, raw_path)
                urls.append(url)
                print(url)
            if args.copy:
                copied = copy_text_to_clipboard("\n".join(urls))
                print(f"clipboard={str(copied).lower()}")
                if copied:
                    send_desktop_notification("CloudBridge", "Public links copied to clipboard.")
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
        return 1
    finally:
        await manager.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(run(args))


def _default_installed_launcher_command() -> str:
    resolved = shutil.which("cloudbridge")
    if resolved:
        return resolved
    return "cloudbridge"
