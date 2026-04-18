import os
import subprocess
from pathlib import Path
from typing import List, Optional
from urllib.parse import unquote, urlparse

from gi.repository import GObject, Nautilus


MENU_ROOT_NAME = "CloudBridge"
MENU_ROOT_ID = "CloudBridgeNautilus::Root"
ENV_FILE = Path.home() / ".config" / "cloudbridge" / "env"
LOG_FILE = Path.home() / ".cache" / "cloudbridge" / "actions.log"

OPEN_ACTION = ("Open with CloudBridge", "src.cloud_open", "folder-cloud")
STORE_LOCAL_ACTION = ("Store Locally", "src.keep_local", "document-save")
RESTORE_CLOUD_ACTION = ("Restore to Cloud", "src.restore_cloud", "folder-cloud")
SHARE_READ_ACTION = ("Create Read-only Link", "src.share_link", "emblem-shared")
ACTIONS = [
    OPEN_ACTION,
    STORE_LOCAL_ACTION,
    RESTORE_CLOUD_ACTION,
    SHARE_READ_ACTION,
]


def _path_from_file_info(file_info: Nautilus.FileInfo) -> Optional[str]:
    uri = file_info.get_uri()
    if not uri:
        return None

    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    return unquote(parsed.path)


def _launch_action(module_name: str, local_path: str) -> None:
    script = f"""
set -euo pipefail
mkdir -p "{LOG_FILE.parent}"
if [ ! -f "{ENV_FILE}" ]; then
  printf '[CloudBridge] missing env file: %s\\n' "{ENV_FILE}" >> "{LOG_FILE}"
  exit 1
fi
source "{ENV_FILE}"
cd "${{CLOUDBRIDGE_PROJECT_DIR}}"
"${{CLOUDBRIDGE_PYTHON}}" -m {module_name} "$1" >> "{LOG_FILE}" 2>&1
"""
    subprocess.Popen(
        ["bash", "-lc", script, "cloudbridge-action", local_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class CloudBridgeExtension(GObject.GObject, Nautilus.MenuProvider):
    def _build_action_item(self, action_id: str, label: str, icon: str, module_name: str, local_path: str):
        item = Nautilus.MenuItem(
            name=action_id,
            label=label,
            tip="",
            icon=icon,
        )
        item.connect("activate", self._on_activate, module_name, local_path)
        return item

    def _on_activate(self, menu: Nautilus.MenuItem, module_name: str, local_path: str) -> None:
        _launch_action(module_name, local_path)

    def get_file_items(self, files: List[Nautilus.FileInfo]):
        if len(files) != 1:
            return []

        local_path = _path_from_file_info(files[0])
        if not local_path or os.path.isdir(local_path):
            return []

        root_item = Nautilus.MenuItem(
            name=MENU_ROOT_ID,
            label=MENU_ROOT_NAME,
            tip="CloudBridge actions",
            icon="folder-cloud",
        )
        submenu = Nautilus.Menu()
        root_item.set_submenu(submenu)

        for index, (label, module_name, icon) in enumerate(ACTIONS, start=1):
            submenu.append_item(
                self._build_action_item(
                    action_id=f"{MENU_ROOT_ID}::{index}",
                    label=label,
                    icon=icon,
                    module_name=module_name,
                    local_path=local_path,
                )
            )

        return [root_item]

    def get_background_items(self, current_folder: Nautilus.FileInfo):
        return []
