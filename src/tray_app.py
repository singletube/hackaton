import json
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .config import load_runtime_config, write_status
from .core.env_config import load_env_file

logger = logging.getLogger(__name__)


def _read_status(path: str) -> dict:
    status_path = Path(path)
    if not status_path.exists():
        return {"state": "stopped", "message": "Status file not found"}
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"state": "error", "message": f"Bad status file: {exc}"}


def _pid_alive(pid_path: str) -> bool:
    path = Path(pid_path)
    if not path.exists():
        return False
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _notify(title: str, message: str):
    if not shutil_which("notify-send"):
        return
    subprocess.run(["notify-send", title, message], check=False)


def shutil_which(name: str) -> Optional[str]:
    for directory in os.getenv("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


class TrayApp:
    def __init__(self):
        load_env_file()
        self.config = load_runtime_config()
        self.python_bin = os.getenv("CLOUDBRIDGE_PYTHON", sys.executable)
        self.project_dir = os.getenv("CLOUDBRIDGE_PROJECT_DIR", str(Path(__file__).resolve().parents[1]))
        self.daemon_proc: Optional[subprocess.Popen] = None

        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk

        self.GLib = GLib
        self.Gtk = Gtk
        self.app_indicator = self._load_appindicator(gi)
        self.status_label = None
        self.start_item = None
        self.stop_item = None

    def _load_appindicator(self, gi):
        for module_name in ("AyatanaAppIndicator3", "AppIndicator3"):
            try:
                gi.require_version(module_name, "0.1")
                module = __import__("gi.repository", fromlist=[module_name])
                return getattr(module, module_name)
            except Exception:
                continue
        return None

    def _build_menu(self):
        menu = self.Gtk.Menu()

        self.status_label = self.Gtk.MenuItem(label="Status: unknown")
        self.status_label.set_sensitive(False)
        menu.append(self.status_label)

        menu.append(self.Gtk.SeparatorMenuItem())

        self.start_item = self.Gtk.MenuItem(label="Start CloudBridge")
        self.start_item.connect("activate", self.on_start_clicked)
        menu.append(self.start_item)

        self.stop_item = self.Gtk.MenuItem(label="Stop CloudBridge")
        self.stop_item.connect("activate", self.on_stop_clicked)
        menu.append(self.stop_item)

        open_mount = self.Gtk.MenuItem(label="Open Mounted Folder")
        open_mount.connect("activate", self.on_open_mount)
        menu.append(open_mount)

        open_log = self.Gtk.MenuItem(label="Open Log")
        open_log.connect("activate", self.on_open_log)
        menu.append(open_log)

        menu.append(self.Gtk.SeparatorMenuItem())
        quick_actions = self.Gtk.MenuItem(label="Quick Actions")
        quick_actions_submenu = self.Gtk.Menu()

        action_share = self.Gtk.MenuItem(label="Share Link...")
        action_share.connect("activate", self.on_share_link)
        quick_actions_submenu.append(action_share)

        action_keep = self.Gtk.MenuItem(label="Store Locally...")
        action_keep.connect("activate", self.on_store_local)
        quick_actions_submenu.append(action_keep)

        action_restore = self.Gtk.MenuItem(label="Restore to Cloud...")
        action_restore.connect("activate", self.on_restore_cloud)
        quick_actions_submenu.append(action_restore)

        quick_actions.set_submenu(quick_actions_submenu)
        menu.append(quick_actions)

        menu.append(self.Gtk.SeparatorMenuItem())
        quit_item = self.Gtk.MenuItem(label="Quit Tray")
        quit_item.connect("activate", self.on_quit)
        menu.append(quit_item)

        menu.show_all()
        return menu

    def _prompt_path(self, title: str) -> Optional[str]:
        if shutil_which("zenity"):
            result = subprocess.run(
                ["zenity", "--entry", "--title", "CloudBridge", "--text", title],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                value = result.stdout.strip()
                return value if value else None
            return None

        _notify("CloudBridge", "Install zenity for quick action path input")
        return None

    def _run_module(self, module: str, path_arg: str):
        command = [self.python_bin, "-m", module, path_arg]
        subprocess.Popen(command, cwd=self.project_dir)

    def _start_daemon(self):
        if self._daemon_running():
            _notify("CloudBridge", "Daemon is already running")
            return
        log_file = Path(self.config.daemon_log_path)
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_file.open("a", encoding="utf-8")
        except OSError:
            fallback_dir = Path(os.getenv("XDG_CACHE_HOME", "~/.cache")).expanduser() / "cloudbridge"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            log_file = fallback_dir / "cloudbridge-daemon.log"
            log_handle = log_file.open("a", encoding="utf-8")
            self.config.daemon_log_path = str(log_file)
            os.environ["CLOUDBRIDGE_DAEMON_LOG"] = str(log_file)
        self.daemon_proc = subprocess.Popen(
            [self.python_bin, "-m", "src.main"],
            cwd=self.project_dir,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        write_status(self.config.status_path, "starting", message="Started from tray")
        _notify("CloudBridge", "Daemon started")

    def _stop_daemon(self):
        pid_path = Path(self.config.pid_path)
        if not pid_path.exists():
            _notify("CloudBridge", "Daemon is not running")
            return
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
            os.kill(pid, signal.SIGTERM)
            write_status(self.config.status_path, "stopping", message="Stopped from tray")
            _notify("CloudBridge", "Stopping daemon")
        except Exception as exc:
            _notify("CloudBridge", f"Failed to stop daemon: {exc}")

    def _daemon_running(self) -> bool:
        return _pid_alive(self.config.pid_path)

    def _refresh_state(self):
        status_data = _read_status(self.config.status_path)
        state = status_data.get("state", "unknown")
        message = status_data.get("message", "")
        is_running = self._daemon_running()
        if not is_running and state == "running":
            state = "stopped"
        if self.status_label:
            suffix = f" ({message})" if message else ""
            self.status_label.set_label(f"Status: {state}{suffix}")
        if self.start_item:
            self.start_item.set_sensitive(not is_running)
        if self.stop_item:
            self.stop_item.set_sensitive(is_running)
        return True

    def on_start_clicked(self, *_args):
        self._start_daemon()
        self._refresh_state()

    def on_stop_clicked(self, *_args):
        self._stop_daemon()
        self._refresh_state()

    def on_open_mount(self, *_args):
        subprocess.run(["xdg-open", self.config.mount_point], check=False)

    def on_open_log(self, *_args):
        subprocess.run(["xdg-open", self.config.daemon_log_path], check=False)

    def on_share_link(self, *_args):
        path_arg = self._prompt_path("Enter local placeholder path or remote path for share link")
        if path_arg:
            self._run_module("src.share_link", path_arg)

    def on_store_local(self, *_args):
        path_arg = self._prompt_path("Enter local placeholder path or remote path to store locally")
        if path_arg:
            self._run_module("src.keep_local", path_arg)

    def on_restore_cloud(self, *_args):
        path_arg = self._prompt_path("Enter local path or remote path to restore to cloud")
        if path_arg:
            self._run_module("src.restore_cloud", path_arg)

    def on_quit(self, *_args):
        self.Gtk.main_quit()

    def run(self):
        menu = self._build_menu()
        if self.app_indicator is not None:
            indicator = self.app_indicator.Indicator.new(
                "cloudbridge-tray",
                "folder-remote",
                self.app_indicator.IndicatorCategory.APPLICATION_STATUS,
            )
            indicator.set_status(self.app_indicator.IndicatorStatus.ACTIVE)
            indicator.set_menu(menu)
        else:
            # Fallback for desktops where AppIndicator is unavailable.
            status_icon = self.Gtk.StatusIcon()
            status_icon.set_from_icon_name("folder-remote")
            status_icon.set_tooltip_text("CloudBridge")
            status_icon.connect("popup-menu", lambda _icon, button, activate_time: menu.popup(None, None, None, None, button, activate_time))
            status_icon.set_visible(True)

        self._refresh_state()
        self.GLib.timeout_add_seconds(5, self._refresh_state)
        self.Gtk.main()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    app = TrayApp()
    app.run()


if __name__ == "__main__":
    main()

