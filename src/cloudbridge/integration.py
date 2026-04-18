from __future__ import annotations

import os
import shlex
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from xml.etree import ElementTree

from .config import AppConfig


@dataclass(slots=True, frozen=True)
class NautilusInstallResult:
    extension_path: Path
    launcher_path: Path


@dataclass(slots=True, frozen=True)
class ThunarInstallResult:
    config_path: Path
    launcher_path: Path


@dataclass(slots=True, frozen=True)
class NemoInstallResult:
    action_paths: tuple[Path, ...]
    launcher_path: Path


@dataclass(slots=True, frozen=True)
class CajaInstallResult:
    extension_path: Path
    action_paths: tuple[Path, ...]
    launcher_path: Path


@dataclass(slots=True, frozen=True)
class ServiceInstallResult:
    unit_path: Path
    launcher_path: Path
    service_name: str


def render_launcher_script(config: AppConfig, command: Sequence[str], *, workdir: Path | None = None) -> str:
    exports = {
        "CLOUDBRIDGE_HOME": str(config.app_home),
        "CLOUDBRIDGE_SYNC_ROOT": str(config.sync_root),
        "CLOUDBRIDGE_DATABASE": str(config.database_path),
        "CLOUDBRIDGE_PROVIDER": config.provider_name,
        "CLOUDBRIDGE_IMPORT_ROOT": config.import_root,
        "CLOUDBRIDGE_IMPORT_LAYOUT": config.import_layout,
        "CLOUDBRIDGE_WATCHER_BACKEND": config.watcher_backend,
        "CLOUDBRIDGE_SCAN_CONCURRENCY": str(config.scan_concurrency),
        "CLOUDBRIDGE_SYNC_CONCURRENCY": str(config.sync_concurrency),
    }
    if config.config_path is not None:
        exports["CLOUDBRIDGE_CONFIG"] = str(config.config_path)
    if config.yandex_token:
        exports["YANDEX_DISK_TOKEN"] = config.yandex_token
    if config.yandex_client_id:
        exports["YANDEX_CLIENT_ID"] = config.yandex_client_id
    if config.yandex_client_secret:
        exports["YANDEX_CLIENT_SECRET"] = config.yandex_client_secret
    if config.nextcloud_url:
        exports["NEXTCLOUD_URL"] = config.nextcloud_url
    if config.nextcloud_username:
        exports["NEXTCLOUD_USERNAME"] = config.nextcloud_username
    if config.nextcloud_password:
        exports["NEXTCLOUD_PASSWORD"] = config.nextcloud_password

    lines = ["#!/usr/bin/env bash", "set -euo pipefail"]
    for key, value in exports.items():
        lines.append(f"export {key}={shlex.quote(value)}")
    if workdir is not None:
        lines.append(f"cd {shlex.quote(str(workdir))}")
    lines.append("exec " + " ".join(shlex.quote(part) for part in command) + ' "$@"')
    return "\n".join(lines) + "\n"


def render_nautilus_extension(launcher_path: Path, sync_root: Path, database_path: Path) -> str:
    return f"""from gi.repository import GObject, Nautilus
import subprocess
import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlparse

LAUNCHER = Path({str(launcher_path)!r})
SYNC_ROOT = Path({str(sync_root)!r}).resolve()
DATABASE_PATH = Path({str(database_path)!r}).resolve()
STATUS_EMBLEMS = {{
    "placeholder": "emblem-downloads",
    "queued": "emblem-synchronizing",
    "syncing": "emblem-synchronizing",
    "error": "emblem-important",
    "local_only": "emblem-new",
}}


def _uri_to_path(uri):
    if not uri or not uri.startswith("file://"):
        return None
    return Path(unquote(urlparse(uri).path)).resolve()


def _collapse_paths(paths):
    collapsed = []
    for path in sorted(set(paths), key=lambda value: len(value.parts)):
        if any(parent == path or parent in path.parents for parent in collapsed):
            continue
        collapsed.append(path)
    return tuple(collapsed)


def _local_to_virtual(path):
    try:
        relative = path.relative_to(SYNC_ROOT)
    except ValueError:
        return None
    if not relative.parts:
        return "/"
    return "/" + "/".join(relative.parts)


def _query_state(path):
    if not DATABASE_PATH.exists():
        return None
    try:
        connection = sqlite3.connect(f"file:{{DATABASE_PATH}}?mode=ro", uri=True, timeout=0.1)
        connection.row_factory = sqlite3.Row
    except sqlite3.Error:
        return None
    try:
        row = connection.execute(
            "SELECT sync_state, public_url, provider FROM entries WHERE path = ?",
            (path,),
        ).fetchone()
        return row
    except sqlite3.Error:
        return None
    finally:
        connection.close()


class CloudBridgeMenuProvider(GObject.GObject, Nautilus.MenuProvider, Nautilus.InfoProvider):
    def _selected_paths(self, files, require_sync_root=False):
        paths = []
        for file_info in files:
            path = _uri_to_path(file_info.get_uri())
            if path is None:
                return ()
            if require_sync_root:
                try:
                    path.relative_to(SYNC_ROOT)
                except ValueError:
                    return ()
            paths.append(path)
        return _collapse_paths(paths)

    def _launch(self, *args):
        if not LAUNCHER.exists():
            return
        subprocess.Popen([str(LAUNCHER), *args], start_new_session=True)

    def update_file_info(self, file_info):
        path = _uri_to_path(file_info.get_uri())
        if path is None:
            return
        virtual_path = _local_to_virtual(path)
        if virtual_path is None:
            return
        row = _query_state(virtual_path)
        if row is None:
            return
        sync_state = row["sync_state"]
        public_url = row["public_url"]
        provider = row["provider"]
        emblem = STATUS_EMBLEMS.get(sync_state)
        if emblem:
            file_info.add_emblem(emblem)
        if public_url:
            file_info.add_emblem("emblem-shared")
        file_info.add_string_attribute("cloudbridge::sync-state", sync_state)
        if provider:
            file_info.add_string_attribute("cloudbridge::provider", provider)
        if public_url:
            file_info.add_string_attribute("cloudbridge::public-url", public_url)

    def _activate_upload(self, menu, files):
        paths = self._selected_paths(files)
        if not paths:
            return
        self._launch("upload-selected", *[str(path) for path in paths])

    def _activate_download(self, menu, files):
        paths = self._selected_paths(files, require_sync_root=True)
        if not paths:
            return
        self._launch("download", *[str(path) for path in paths])

    def _activate_dehydrate(self, menu, files):
        paths = self._selected_paths(files, require_sync_root=True)
        if not paths:
            return
        self._launch("dehydrate", *[str(path) for path in paths])

    def _activate_share(self, menu, files):
        paths = self._selected_paths(files)
        if not paths:
            return
        self._launch("share-selected", "--copy", *[str(path) for path in paths])

    def get_file_items(self, files):
        paths = self._selected_paths(files)
        if not paths:
            return ()
        sync_paths = self._selected_paths(files, require_sync_root=True)

        root_item = Nautilus.MenuItem(
            name="CloudBridgeMenuProvider::root",
            label="CloudBridge",
            tip="CloudBridge actions",
        )
        submenu = Nautilus.Menu()
        root_item.set_submenu(submenu)

        upload_item = Nautilus.MenuItem(
            name="CloudBridgeMenuProvider::upload",
            label="Upload to Cloud",
            tip="Upload selected files to CloudBridge",
        )
        upload_item.connect("activate", self._activate_upload, files)
        submenu.append_item(upload_item)

        share_item = Nautilus.MenuItem(
            name="CloudBridgeMenuProvider::share",
            label="Copy Public Link",
            tip="Create or reuse a public share link and copy it to the clipboard",
        )
        share_item.connect("activate", self._activate_share, files)
        submenu.append_item(share_item)

        if sync_paths:
            download_item = Nautilus.MenuItem(
                name="CloudBridgeMenuProvider::download",
                label="Download from Cloud",
                tip="Replace placeholders with full local files",
            )
            download_item.connect("activate", self._activate_download, files)
            submenu.append_item(download_item)

            dehydrate_item = Nautilus.MenuItem(
                name="CloudBridgeMenuProvider::dehydrate",
                label="Free Local Space",
                tip="Turn local files back into placeholders",
            )
            dehydrate_item.connect("activate", self._activate_dehydrate, files)
            submenu.append_item(dehydrate_item)

        return (root_item,)
"""


def render_caja_extension(launcher_path: Path, sync_root: Path, database_path: Path) -> str:
    return f"""from gi.repository import GObject, Caja
import subprocess
import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlparse

LAUNCHER = Path({str(launcher_path)!r})
SYNC_ROOT = Path({str(sync_root)!r}).resolve()
DATABASE_PATH = Path({str(database_path)!r}).resolve()
STATUS_EMBLEMS = {{
    "placeholder": "emblem-downloads",
    "queued": "emblem-synchronizing",
    "syncing": "emblem-synchronizing",
    "error": "emblem-important",
    "local_only": "emblem-new",
}}


def _uri_to_path(uri):
    if not uri or not uri.startswith("file://"):
        return None
    return Path(unquote(urlparse(uri).path)).resolve()


def _collapse_paths(paths):
    collapsed = []
    for path in sorted(set(paths), key=lambda value: len(value.parts)):
        if any(parent == path or parent in path.parents for parent in collapsed):
            continue
        collapsed.append(path)
    return tuple(collapsed)


def _local_to_virtual(path):
    try:
        relative = path.relative_to(SYNC_ROOT)
    except ValueError:
        return None
    if not relative.parts:
        return "/"
    return "/" + "/".join(relative.parts)


def _query_state(path):
    if not DATABASE_PATH.exists():
        return None
    try:
        connection = sqlite3.connect(f"file:{{DATABASE_PATH}}?mode=ro", uri=True, timeout=0.1)
        connection.row_factory = sqlite3.Row
    except sqlite3.Error:
        return None
    try:
        row = connection.execute(
            "SELECT sync_state, public_url, provider FROM entries WHERE path = ?",
            (path,),
        ).fetchone()
        return row
    except sqlite3.Error:
        return None
    finally:
        connection.close()


class CloudBridgeCajaProvider(GObject.GObject, Caja.MenuProvider, Caja.InfoProvider):
    def _selected_paths(self, files, require_sync_root=False):
        paths = []
        for file_info in files:
            path = _uri_to_path(file_info.get_uri())
            if path is None:
                return ()
            if require_sync_root:
                try:
                    path.relative_to(SYNC_ROOT)
                except ValueError:
                    return ()
            paths.append(path)
        return _collapse_paths(paths)

    def _launch(self, *args):
        if not LAUNCHER.exists():
            return
        subprocess.Popen([str(LAUNCHER), *args], start_new_session=True)

    def update_file_info(self, file_info):
        path = _uri_to_path(file_info.get_uri())
        if path is None:
            return
        virtual_path = _local_to_virtual(path)
        if virtual_path is None:
            return
        row = _query_state(virtual_path)
        if row is None:
            return
        sync_state = row["sync_state"]
        public_url = row["public_url"]
        provider = row["provider"]
        emblem = STATUS_EMBLEMS.get(sync_state)
        if emblem:
            file_info.add_emblem(emblem)
        if public_url:
            file_info.add_emblem("emblem-shared")
        file_info.add_string_attribute("cloudbridge::sync-state", sync_state)
        if provider:
            file_info.add_string_attribute("cloudbridge::provider", provider)
        if public_url:
            file_info.add_string_attribute("cloudbridge::public-url", public_url)

    def _activate_upload(self, menu, files):
        paths = self._selected_paths(files)
        if not paths:
            return
        self._launch("upload-selected", *[str(path) for path in paths])

    def _activate_download(self, menu, files):
        paths = self._selected_paths(files, require_sync_root=True)
        if not paths:
            return
        self._launch("download", *[str(path) for path in paths])

    def _activate_dehydrate(self, menu, files):
        paths = self._selected_paths(files, require_sync_root=True)
        if not paths:
            return
        self._launch("dehydrate", *[str(path) for path in paths])

    def _activate_share(self, menu, files):
        paths = self._selected_paths(files)
        if not paths:
            return
        self._launch("share-selected", "--copy", *[str(path) for path in paths])

    def get_file_items(self, window, files):
        paths = self._selected_paths(files)
        if not paths:
            return ()
        sync_paths = self._selected_paths(files, require_sync_root=True)

        root_item = Caja.MenuItem(
            name="CloudBridgeCajaProvider::root",
            label="CloudBridge",
            tip="CloudBridge actions",
        )
        submenu = Caja.Menu()
        root_item.set_submenu(submenu)

        upload_item = Caja.MenuItem(
            name="CloudBridgeCajaProvider::upload",
            label="Upload to Cloud",
            tip="Upload selected files to CloudBridge",
        )
        upload_item.connect("activate", self._activate_upload, files)
        submenu.append_item(upload_item)

        share_item = Caja.MenuItem(
            name="CloudBridgeCajaProvider::share",
            label="Copy Public Link",
            tip="Create or reuse a public share link and copy it to the clipboard",
        )
        share_item.connect("activate", self._activate_share, files)
        submenu.append_item(share_item)

        if sync_paths:
            download_item = Caja.MenuItem(
                name="CloudBridgeCajaProvider::download",
                label="Download from Cloud",
                tip="Replace placeholders with full local files",
            )
            download_item.connect("activate", self._activate_download, files)
            submenu.append_item(download_item)

            dehydrate_item = Caja.MenuItem(
                name="CloudBridgeCajaProvider::dehydrate",
                label="Free Local Space",
                tip="Turn local files back into placeholders",
            )
            dehydrate_item.connect("activate", self._activate_dehydrate, files)
            submenu.append_item(dehydrate_item)

        return (root_item,)
"""


def render_thunar_uca_xml(launcher_path: Path, existing_xml: str | None = None) -> str:
    marker = "cloudbridge-managed"
    if existing_xml:
        try:
            root = ElementTree.fromstring(existing_xml)
        except ElementTree.ParseError:
            root = ElementTree.Element("actions")
    else:
        root = ElementTree.Element("actions")
    if root.tag != "actions":
        root = ElementTree.Element("actions")

    for action in list(root.findall("action")):
        name = (action.findtext("name") or "").strip()
        description = (action.findtext("description") or "").strip()
        command = (action.findtext("command") or "").strip()
        if marker in description or name.startswith("CloudBridge ") or str(launcher_path) in command:
            root.remove(action)

    _append_thunar_action(
        root,
        icon="folder-remote",
        name="CloudBridge Upload to Cloud",
        unique_id="cloudbridge-upload-to-cloud",
        command=f"{shlex.quote(str(launcher_path))} upload-selected %F",
        description="Upload selected files to CloudBridge [cloudbridge-managed]",
    )
    _append_thunar_action(
        root,
        icon="emblem-shared",
        name="CloudBridge Copy Public Link",
        unique_id="cloudbridge-copy-public-link",
        command=f"{shlex.quote(str(launcher_path))} share-selected --copy %F",
        description="Create or reuse a public CloudBridge link [cloudbridge-managed]",
    )
    _append_thunar_action(
        root,
        icon="emblem-downloads",
        name="CloudBridge Download from Cloud",
        unique_id="cloudbridge-download-from-cloud",
        command=f"{shlex.quote(str(launcher_path))} download %F",
        description="Replace CloudBridge placeholders with full local files [cloudbridge-managed]",
    )
    _append_thunar_action(
        root,
        icon="user-trash",
        name="CloudBridge Free Local Space",
        unique_id="cloudbridge-free-local-space",
        command=f"{shlex.quote(str(launcher_path))} dehydrate %F",
        description="Turn local CloudBridge files back into placeholders [cloudbridge-managed]",
    )

    tree = ElementTree.ElementTree(root)
    ElementTree.indent(tree, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ElementTree.tostring(root, encoding="unicode")


def render_nemo_action(launcher_path: Path) -> str:
    return (
        "[Nemo Action]\n"
        "Active=true\n"
        "Name=CloudBridge Upload to Cloud\n"
        "Comment=Upload selected files to CloudBridge\n"
        f"Exec={shlex.quote(str(launcher_path))} upload-selected %F\n"
        "Icon-Name=folder-remote\n"
        "Selection=notnone\n"
        "Extensions=any;\n"
        "Quote=double\n"
        "EscapeSpaces=true\n"
    )


def render_nemo_share_action(launcher_path: Path) -> str:
    return (
        "[Nemo Action]\n"
        "Active=true\n"
        "Name=CloudBridge Copy Public Link\n"
        "Comment=Create or reuse a public CloudBridge link\n"
        f"Exec={shlex.quote(str(launcher_path))} share-selected --copy %F\n"
        "Icon-Name=emblem-shared\n"
        "Selection=notnone\n"
        "Extensions=any;\n"
        "Quote=double\n"
        "EscapeSpaces=true\n"
    )


def render_nemo_download_action(launcher_path: Path) -> str:
    return (
        "[Nemo Action]\n"
        "Active=true\n"
        "Name=CloudBridge Download from Cloud\n"
        "Comment=Replace CloudBridge placeholders with full local files\n"
        f"Exec={shlex.quote(str(launcher_path))} download %F\n"
        "Icon-Name=emblem-downloads\n"
        "Selection=notnone\n"
        "Extensions=any;\n"
        "Quote=double\n"
        "EscapeSpaces=true\n"
    )


def render_nemo_dehydrate_action(launcher_path: Path) -> str:
    return (
        "[Nemo Action]\n"
        "Active=true\n"
        "Name=CloudBridge Free Local Space\n"
        "Comment=Turn local CloudBridge files back into placeholders\n"
        f"Exec={shlex.quote(str(launcher_path))} dehydrate %F\n"
        "Icon-Name=user-trash\n"
        "Selection=notnone\n"
        "Extensions=any;\n"
        "Quote=double\n"
        "EscapeSpaces=true\n"
    )


def render_caja_action_desktop(launcher_path: Path) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Action\n"
        "Name=CloudBridge Upload to Cloud\n"
        "Tooltip=Upload selected files to CloudBridge\n"
        "Icon=folder-remote\n"
        "Profiles=profile-zero;\n"
        "\n"
        "[X-Action-Profile profile-zero]\n"
        "Name=Default profile\n"
        "MimeTypes=all/all;\n"
        "SelectionCount=>0\n"
        f"Exec={shlex.quote(str(launcher_path))} upload-selected %F\n"
    )


def render_caja_share_action_desktop(launcher_path: Path) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Action\n"
        "Name=CloudBridge Copy Public Link\n"
        "Tooltip=Create or reuse a public CloudBridge link\n"
        "Icon=emblem-shared\n"
        "Profiles=profile-zero;\n"
        "\n"
        "[X-Action-Profile profile-zero]\n"
        "Name=Default profile\n"
        "MimeTypes=all/all;\n"
        "SelectionCount=>0\n"
        f"Exec={shlex.quote(str(launcher_path))} share-selected --copy %F\n"
    )


def render_caja_download_action_desktop(launcher_path: Path) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Action\n"
        "Name=CloudBridge Download from Cloud\n"
        "Tooltip=Replace CloudBridge placeholders with full local files\n"
        "Icon=emblem-downloads\n"
        "Profiles=profile-zero;\n"
        "\n"
        "[X-Action-Profile profile-zero]\n"
        "Name=Default profile\n"
        "MimeTypes=all/all;\n"
        "SelectionCount=>0\n"
        f"Exec={shlex.quote(str(launcher_path))} download %F\n"
    )


def render_caja_dehydrate_action_desktop(launcher_path: Path) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Action\n"
        "Name=CloudBridge Free Local Space\n"
        "Tooltip=Turn local CloudBridge files back into placeholders\n"
        "Icon=user-trash\n"
        "Profiles=profile-zero;\n"
        "\n"
        "[X-Action-Profile profile-zero]\n"
        "Name=Default profile\n"
        "MimeTypes=all/all;\n"
        "SelectionCount=>0\n"
        f"Exec={shlex.quote(str(launcher_path))} dehydrate %F\n"
    )


def render_systemd_user_service(
    launcher_path: Path,
    *,
    service_name: str = "cloudbridge",
    poll_interval: float = 2.0,
    refresh_interval: float = 30.0,
) -> str:
    return (
        "[Unit]\n"
        f"Description=CloudBridge background sync service ({service_name})\n"
        "After=default.target network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={shlex.quote(str(launcher_path))} daemon --poll-interval {poll_interval:g} --refresh-interval {refresh_interval:g}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _resolve_uv_path(uv_path: str | None) -> Path:
    resolved_uv_raw = uv_path or shutil.which("uv")
    if not resolved_uv_raw:
        raise FileNotFoundError("uv executable was not found. Install uv or pass --uv-path.")
    resolved_uv = Path(resolved_uv_raw).expanduser()
    if not resolved_uv.exists():
        raise FileNotFoundError(f"uv executable was not found: {resolved_uv}")
    return resolved_uv


def _resolve_launcher_runtime(
    *,
    repo_root: Path | None,
    uv_path: str | None,
    launcher_command: str | None,
) -> tuple[list[str], Path | None]:
    if launcher_command:
        command = shlex.split(launcher_command)
        if not command:
            raise ValueError("launcher_command must not be empty.")
        return command, None
    if repo_root is None:
        raise ValueError("repo_root is required when launcher_command is not provided.")
    resolved_uv = _resolve_uv_path(uv_path)
    resolved_repo_root = repo_root.expanduser().resolve()
    return [
        str(resolved_uv.resolve()),
        "run",
        "--project",
        str(resolved_repo_root),
        "cloudbridge",
    ], resolved_repo_root


def install_nautilus_integration(
    config: AppConfig,
    *,
    repo_root: Path | None,
    uv_path: str | None = None,
    launcher_command: str | None = None,
    extension_dir: Path | None = None,
    launcher_path: Path | None = None,
) -> NautilusInstallResult:
    _validate_provider_credentials(config, "install Nautilus integration")

    command, workdir = _resolve_launcher_runtime(
        repo_root=repo_root,
        uv_path=uv_path,
        launcher_command=launcher_command,
    )
    extension_dir = (extension_dir or Path.home() / ".local" / "share" / "nautilus-python" / "extensions").expanduser()
    launcher_path = (launcher_path or config.app_home / "bin" / "cloudbridge-nautilus").expanduser()
    extension_path = extension_dir / "cloudbridge_menu.py"

    extension_dir.mkdir(parents=True, exist_ok=True)
    launcher_path.parent.mkdir(parents=True, exist_ok=True)

    launcher_path.write_text(render_launcher_script(config, command, workdir=workdir), encoding="utf-8")
    extension_path.write_text(
        render_nautilus_extension(
            launcher_path.resolve(),
            config.sync_root.resolve(),
            config.database_path.resolve(),
        ),
        encoding="utf-8",
    )

    launcher_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    extension_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    return NautilusInstallResult(
        extension_path=extension_path.resolve(),
        launcher_path=launcher_path.resolve(),
    )


def install_thunar_integration(
    config: AppConfig,
    *,
    repo_root: Path | None,
    uv_path: str | None = None,
    launcher_command: str | None = None,
    config_path: Path | None = None,
    launcher_path: Path | None = None,
) -> ThunarInstallResult:
    _validate_provider_credentials(config, "install Thunar integration")

    command, workdir = _resolve_launcher_runtime(
        repo_root=repo_root,
        uv_path=uv_path,
        launcher_command=launcher_command,
    )
    config_path = (config_path or Path.home() / ".config" / "Thunar" / "uca.xml").expanduser()
    launcher_path = (launcher_path or config.app_home / "bin" / "cloudbridge-thunar").expanduser()

    config_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_path.parent.mkdir(parents=True, exist_ok=True)

    launcher_path.write_text(render_launcher_script(config, command, workdir=workdir), encoding="utf-8")
    existing_xml = config_path.read_text(encoding="utf-8") if config_path.exists() else None
    config_path.write_text(render_thunar_uca_xml(launcher_path.resolve(), existing_xml), encoding="utf-8")

    launcher_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    config_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    return ThunarInstallResult(
        config_path=config_path.resolve(),
        launcher_path=launcher_path.resolve(),
    )


def install_nemo_integration(
    config: AppConfig,
    *,
    repo_root: Path | None,
    uv_path: str | None = None,
    launcher_command: str | None = None,
    actions_dir: Path | None = None,
    launcher_path: Path | None = None,
) -> NemoInstallResult:
    _validate_provider_credentials(config, "install Nemo integration")

    command, workdir = _resolve_launcher_runtime(
        repo_root=repo_root,
        uv_path=uv_path,
        launcher_command=launcher_command,
    )
    actions_dir = (actions_dir or Path.home() / ".local" / "share" / "nemo" / "actions").expanduser()
    launcher_path = (launcher_path or config.app_home / "bin" / "cloudbridge-nemo").expanduser()
    upload_action_path = actions_dir / "cloudbridge-upload.nemo_action"
    share_action_path = actions_dir / "cloudbridge-share.nemo_action"
    download_action_path = actions_dir / "cloudbridge-download.nemo_action"
    dehydrate_action_path = actions_dir / "cloudbridge-dehydrate.nemo_action"

    actions_dir.mkdir(parents=True, exist_ok=True)
    launcher_path.parent.mkdir(parents=True, exist_ok=True)

    launcher_path.write_text(render_launcher_script(config, command, workdir=workdir), encoding="utf-8")
    upload_action_path.write_text(render_nemo_action(launcher_path.resolve()), encoding="utf-8")
    share_action_path.write_text(render_nemo_share_action(launcher_path.resolve()), encoding="utf-8")
    download_action_path.write_text(render_nemo_download_action(launcher_path.resolve()), encoding="utf-8")
    dehydrate_action_path.write_text(render_nemo_dehydrate_action(launcher_path.resolve()), encoding="utf-8")

    launcher_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    upload_action_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    share_action_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    download_action_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    dehydrate_action_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    return NemoInstallResult(
        action_paths=(
            upload_action_path.resolve(),
            share_action_path.resolve(),
            download_action_path.resolve(),
            dehydrate_action_path.resolve(),
        ),
        launcher_path=launcher_path.resolve(),
    )


def install_caja_integration(
    config: AppConfig,
    *,
    repo_root: Path | None,
    uv_path: str | None = None,
    launcher_command: str | None = None,
    extension_dir: Path | None = None,
    actions_dir: Path | None = None,
    launcher_path: Path | None = None,
) -> CajaInstallResult:
    _validate_provider_credentials(config, "install Caja integration")

    command, workdir = _resolve_launcher_runtime(
        repo_root=repo_root,
        uv_path=uv_path,
        launcher_command=launcher_command,
    )
    extension_dir = (extension_dir or Path.home() / ".local" / "share" / "caja-python" / "extensions").expanduser()
    actions_dir = (actions_dir or Path.home() / ".local" / "share" / "file-manager" / "actions").expanduser()
    launcher_path = (launcher_path or config.app_home / "bin" / "cloudbridge-caja").expanduser()
    extension_path = extension_dir / "cloudbridge_menu.py"
    upload_action_path = actions_dir / "cloudbridge-upload.desktop"
    share_action_path = actions_dir / "cloudbridge-share.desktop"
    download_action_path = actions_dir / "cloudbridge-download.desktop"
    dehydrate_action_path = actions_dir / "cloudbridge-dehydrate.desktop"

    extension_dir.mkdir(parents=True, exist_ok=True)
    actions_dir.mkdir(parents=True, exist_ok=True)
    launcher_path.parent.mkdir(parents=True, exist_ok=True)

    launcher_path.write_text(render_launcher_script(config, command, workdir=workdir), encoding="utf-8")
    extension_path.write_text(
        render_caja_extension(
            launcher_path.resolve(),
            config.sync_root.resolve(),
            config.database_path.resolve(),
        ),
        encoding="utf-8",
    )
    upload_action_path.write_text(render_caja_action_desktop(launcher_path.resolve()), encoding="utf-8")
    share_action_path.write_text(render_caja_share_action_desktop(launcher_path.resolve()), encoding="utf-8")
    download_action_path.write_text(render_caja_download_action_desktop(launcher_path.resolve()), encoding="utf-8")
    dehydrate_action_path.write_text(render_caja_dehydrate_action_desktop(launcher_path.resolve()), encoding="utf-8")

    launcher_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    extension_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    upload_action_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    share_action_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    download_action_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    dehydrate_action_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    return CajaInstallResult(
        extension_path=extension_path.resolve(),
        action_paths=(
            upload_action_path.resolve(),
            share_action_path.resolve(),
            download_action_path.resolve(),
            dehydrate_action_path.resolve(),
        ),
        launcher_path=launcher_path.resolve(),
    )


def install_systemd_user_service(
    config: AppConfig,
    *,
    repo_root: Path | None,
    uv_path: str | None = None,
    launcher_command: str | None = None,
    launcher_path: Path | None = None,
    unit_path: Path | None = None,
    service_name: str = "cloudbridge",
    poll_interval: float = 2.0,
    refresh_interval: float = 30.0,
) -> ServiceInstallResult:
    _validate_provider_credentials(config, "install the CloudBridge service")

    command, workdir = _resolve_launcher_runtime(
        repo_root=repo_root,
        uv_path=uv_path,
        launcher_command=launcher_command,
    )
    launcher_path = (launcher_path or config.app_home / "bin" / "cloudbridge-service").expanduser()
    unit_path = (unit_path or Path.home() / ".config" / "systemd" / "user" / f"{service_name}.service").expanduser()

    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    unit_path.parent.mkdir(parents=True, exist_ok=True)

    launcher_path.write_text(render_launcher_script(config, command, workdir=workdir), encoding="utf-8")
    unit_path.write_text(
        render_systemd_user_service(
            launcher_path.resolve(),
            service_name=service_name,
            poll_interval=poll_interval,
            refresh_interval=refresh_interval,
        ),
        encoding="utf-8",
    )

    launcher_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    unit_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    return ServiceInstallResult(
        unit_path=unit_path.resolve(),
        launcher_path=launcher_path.resolve(),
        service_name=service_name,
    )


def detect_file_manager() -> str | None:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    session = os.environ.get("DESKTOP_SESSION", "").lower()
    combined = f"{desktop}:{session}"
    if "gnome" in combined:
        return "nautilus"
    if "cinnamon" in combined:
        return "nemo"
    if "mate" in combined:
        return "caja"
    if "xfce" in combined:
        return "thunar"
    if shutil.which("nautilus"):
        return "nautilus"
    if shutil.which("nemo"):
        return "nemo"
    if shutil.which("caja"):
        return "caja"
    if shutil.which("thunar"):
        return "thunar"
    return None


def _validate_provider_credentials(config: AppConfig, action: str) -> None:
    if config.provider_name == "yandex":
        if config.yandex_token:
            return
        raise ValueError(f"YANDEX_DISK_TOKEN is required to {action} for the Yandex provider.")
    if config.provider_name == "nextcloud":
        if config.nextcloud_url and config.nextcloud_username and config.nextcloud_password:
            return
        raise ValueError(
            f"NEXTCLOUD_URL, NEXTCLOUD_USERNAME, and NEXTCLOUD_PASSWORD are required to {action} for the Nextcloud provider."
        )


def _append_thunar_action(
    root: ElementTree.Element,
    *,
    icon: str,
    name: str,
    unique_id: str,
    command: str,
    description: str,
) -> None:
    action = ElementTree.SubElement(root, "action")
    ElementTree.SubElement(action, "icon").text = icon
    ElementTree.SubElement(action, "name").text = name
    ElementTree.SubElement(action, "unique-id").text = unique_id
    ElementTree.SubElement(action, "command").text = command
    ElementTree.SubElement(action, "description").text = description
    ElementTree.SubElement(action, "patterns").text = "*"
    ElementTree.SubElement(action, "range").text = "1-*"
    ElementTree.SubElement(action, "startup-notify")
    ElementTree.SubElement(action, "directories")
    ElementTree.SubElement(action, "other-files")
