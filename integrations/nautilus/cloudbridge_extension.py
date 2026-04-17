from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from cloudbridge.config import load_settings

try:
    from gi.repository import GObject, Nautilus
except ImportError as exc:  # pragma: no cover - runs only inside Nautilus
    raise ImportError("nautilus-python is required for the Nautilus extension") from exc


class CloudBridgeMenuProvider(GObject.GObject, Nautilus.MenuProvider, Nautilus.InfoProvider):  # pragma: no cover - desktop integration
    def __init__(self) -> None:
        super().__init__()
        self._settings = load_settings()
        self._python = sys.executable or "python3"

    def update_file_info(self, file_info):
        target = self._get_local_path(file_info)
        if target is None:
            return

        if target.is_file() and target.stat().st_size == 0:
            # It's likely a placeholder
            file_info.add_emblem("emblem-web")
            file_info.add_string_attribute("cloudbridge_status", "Online-Only")

    def get_file_items(self, files):
        if not files:
            return ()

        target = self._get_local_path(files[0])
        if target is None:
            return ()

        items = [
            self._menu_item(
                "CloudBridge::Sync",
                "CloudBridge: Sync Now",
                "Run synchronization for CloudBridge",
                self._run_command,
                ["sync"],
            ),
            self._menu_item(
                "CloudBridge::GUI",
                "CloudBridge: Open Dashboard",
                "Open the CloudBridge desktop window",
                self._run_command,
                ["gui"],
            ),
            self._menu_item(
                "CloudBridge::Share",
                "CloudBridge: Share Link",
                "Create a public link for the selected file",
                self._run_share,
                [target],
            ),
        ]

        if target.is_file():
            if target.stat().st_size == 0:
                items.append(
                    self._menu_item(
                        "CloudBridge::BringOffline",
                        "CloudBridge: Bring Offline",
                        "Download full file content",
                        self._run_bring_offline,
                        [target],
                    )
                )
            else:
                items.append(
                    self._menu_item(
                        "CloudBridge::MakeOnline",
                        "CloudBridge: Make Online-Only",
                        "Keep only a 0-byte placeholder locally",
                        self._run_make_online,
                        [target],
                    )
                )

        items.extend([
            self._menu_item(
                "CloudBridge::Pin",
                "CloudBridge: Pin Offline",
                "Mark the file for offline access",
                self._run_pin,
                [target, True],
            ),
            self._menu_item(
                "CloudBridge::Unpin",
                "CloudBridge: Unpin Offline",
                "Remove offline pin from the file",
                self._run_pin,
                [target, False],
            ),
        ])
        return tuple(items)

    def _menu_item(self, item_id, label, tip, callback, args):
        item = Nautilus.MenuItem(name=item_id, label=label, tip=tip)
        item.connect("activate", callback, *args)
        return item

    def _run_command(self, _menu, *args):
        subprocess.Popen([self._python, "-m", "cloudbridge", *args])

    def _run_share(self, _menu, local_path: Path):
        rel = local_path.resolve().relative_to(self._settings.local_root).as_posix()
        subprocess.Popen(
            [self._python, "-m", "cloudbridge", "share", self._to_cloud_path(rel)]
        )

    def _run_pin(self, _menu, local_path: Path, pin: bool):
        rel = local_path.resolve().relative_to(self._settings.local_root).as_posix()
        command = "pin" if pin else "unpin"
        subprocess.Popen([self._python, "-m", "cloudbridge", command, rel])

    def _run_make_online(self, _menu, local_path: Path):
        rel = local_path.resolve().relative_to(self._settings.local_root).as_posix()
        subprocess.Popen([self._python, "-m", "cloudbridge", "make-online-only", rel])

    def _run_bring_offline(self, _menu, local_path: Path):
        rel = local_path.resolve().relative_to(self._settings.local_root).as_posix()
        subprocess.Popen([self._python, "-m", "cloudbridge", "bring-offline", rel])

    def _get_local_path(self, file_info) -> Path | None:
        location = file_info.get_location()
        if location is None:
            return None
        path = location.get_path()
        if not path:
            return None
        candidate = Path(path).resolve()
        try:
            candidate.relative_to(self._settings.local_root)
        except ValueError:
            return None
        return candidate

    def _to_cloud_path(self, rel_path: str) -> str:
        rel = rel_path.strip("/")
        root = self._settings.cloud_root.strip()
        if root in ("disk:", "disk:/"):
            return "disk:/" if not rel else f"disk:/{rel}"
        if not root:
            return rel
        return root if not rel else f"{root.rstrip('/')}/{rel}"
