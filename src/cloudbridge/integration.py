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
    action_path: Path
    launcher_path: Path


@dataclass(slots=True, frozen=True)
class CajaInstallResult:
    action_path: Path
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
    if config.yandex_token:
        exports["YANDEX_DISK_TOKEN"] = config.yandex_token

    lines = ["#!/usr/bin/env bash", "set -euo pipefail"]
    for key, value in exports.items():
        lines.append(f"export {key}={shlex.quote(value)}")
    if workdir is not None:
        lines.append(f"cd {shlex.quote(str(workdir))}")
    lines.append("exec " + " ".join(shlex.quote(part) for part in command) + ' "$@"')
    return "\n".join(lines) + "\n"


def render_nautilus_extension(launcher_path: Path, sync_root: Path) -> str:
    return f"""from gi.repository import GObject, Nautilus
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

LAUNCHER = Path({str(launcher_path)!r})
SYNC_ROOT = Path({str(sync_root)!r}).resolve()


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


class CloudBridgeMenuProvider(GObject.GObject, Nautilus.MenuProvider):
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

    action = ElementTree.SubElement(root, "action")
    ElementTree.SubElement(action, "icon").text = "folder-remote"
    ElementTree.SubElement(action, "name").text = "CloudBridge Upload to Cloud"
    ElementTree.SubElement(action, "unique-id").text = "cloudbridge-upload-to-cloud"
    ElementTree.SubElement(action, "command").text = f"{shlex.quote(str(launcher_path))} upload-selected %F"
    ElementTree.SubElement(action, "description").text = "Upload selected files to CloudBridge [cloudbridge-managed]"
    ElementTree.SubElement(action, "patterns").text = "*"
    ElementTree.SubElement(action, "range").text = "1-*"
    ElementTree.SubElement(action, "startup-notify")
    ElementTree.SubElement(action, "directories")
    ElementTree.SubElement(action, "other-files")

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
    if config.provider_name == "yandex" and not config.yandex_token:
        raise ValueError("YANDEX_DISK_TOKEN is required to install Nautilus integration for the Yandex provider.")

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
    extension_path.write_text(render_nautilus_extension(launcher_path.resolve(), config.sync_root.resolve()), encoding="utf-8")

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
    if config.provider_name == "yandex" and not config.yandex_token:
        raise ValueError("YANDEX_DISK_TOKEN is required to install Thunar integration for the Yandex provider.")

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
    if config.provider_name == "yandex" and not config.yandex_token:
        raise ValueError("YANDEX_DISK_TOKEN is required to install Nemo integration for the Yandex provider.")

    command, workdir = _resolve_launcher_runtime(
        repo_root=repo_root,
        uv_path=uv_path,
        launcher_command=launcher_command,
    )
    actions_dir = (actions_dir or Path.home() / ".local" / "share" / "nemo" / "actions").expanduser()
    launcher_path = (launcher_path or config.app_home / "bin" / "cloudbridge-nemo").expanduser()
    action_path = actions_dir / "cloudbridge-upload.nemo_action"

    actions_dir.mkdir(parents=True, exist_ok=True)
    launcher_path.parent.mkdir(parents=True, exist_ok=True)

    launcher_path.write_text(render_launcher_script(config, command, workdir=workdir), encoding="utf-8")
    action_path.write_text(render_nemo_action(launcher_path.resolve()), encoding="utf-8")

    launcher_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    action_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    return NemoInstallResult(
        action_path=action_path.resolve(),
        launcher_path=launcher_path.resolve(),
    )


def install_caja_integration(
    config: AppConfig,
    *,
    repo_root: Path | None,
    uv_path: str | None = None,
    launcher_command: str | None = None,
    actions_dir: Path | None = None,
    launcher_path: Path | None = None,
) -> CajaInstallResult:
    if config.provider_name == "yandex" and not config.yandex_token:
        raise ValueError("YANDEX_DISK_TOKEN is required to install Caja integration for the Yandex provider.")

    command, workdir = _resolve_launcher_runtime(
        repo_root=repo_root,
        uv_path=uv_path,
        launcher_command=launcher_command,
    )
    actions_dir = (actions_dir or Path.home() / ".local" / "share" / "file-manager" / "actions").expanduser()
    launcher_path = (launcher_path or config.app_home / "bin" / "cloudbridge-caja").expanduser()
    action_path = actions_dir / "cloudbridge-upload.desktop"

    actions_dir.mkdir(parents=True, exist_ok=True)
    launcher_path.parent.mkdir(parents=True, exist_ok=True)

    launcher_path.write_text(render_launcher_script(config, command, workdir=workdir), encoding="utf-8")
    action_path.write_text(render_caja_action_desktop(launcher_path.resolve()), encoding="utf-8")

    launcher_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    action_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    return CajaInstallResult(
        action_path=action_path.resolve(),
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
    if config.provider_name == "yandex" and not config.yandex_token:
        raise ValueError("YANDEX_DISK_TOKEN is required to install the CloudBridge service for the Yandex provider.")

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
