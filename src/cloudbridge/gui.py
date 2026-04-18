from __future__ import annotations

import asyncio
import queue
import shutil
import subprocess
import sys
import threading
import webbrowser
from dataclasses import replace
from pathlib import Path
from typing import Callable

from .clipboard import copy_text_to_clipboard
from .config import AppConfig
from .hybrid import HybridManager
from .integration import (
    detect_file_manager,
    install_caja_integration,
    install_nautilus_integration,
    install_nemo_integration,
    install_systemd_user_service,
    install_thunar_integration,
)
from .providers import NextcloudProvider, YandexDiskProvider
from .setup import run_nextcloud_login_flow, run_yandex_device_login_flow

BASEALT_RED = "#D7282F"
BASEALT_RED_DARK = "#B61F26"
BASEALT_GRAPHITE = "#20252D"
BASEALT_PAPER = "#F5F1EC"
BASEALT_PANEL = "#FFFDFC"
BASEALT_BORDER = "#D9CDC2"
BASEALT_TEXT = "#221F1D"
BASEALT_MUTED = "#6D625B"


def default_gui_launcher_command(argv0: str | None = None) -> str:
    candidate = (argv0 or sys.argv[0] or "").strip()
    if candidate:
        candidate_path = Path(candidate).expanduser()
        if candidate_path.is_absolute() and candidate_path.exists():
            return str(candidate_path)
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    for fallback in ("cloudbridge-local", "cloudbridge"):
        resolved = shutil.which(fallback)
        if resolved:
            return resolved
    return "cloudbridge"


def build_gui_config(
    base_config: AppConfig,
    *,
    provider_name: str,
    sync_root: str,
    import_root: str,
    import_layout: str,
    watcher_backend: str,
    scan_concurrency: int,
    sync_concurrency: int,
    yandex_token: str | None,
    yandex_client_id: str | None,
    yandex_client_secret: str | None,
    nextcloud_url: str | None,
    nextcloud_username: str | None,
    nextcloud_password: str | None,
) -> AppConfig:
    return replace(
        base_config,
        provider_name=provider_name.strip().lower(),
        sync_root=Path(sync_root).expanduser(),
        import_root=import_root.strip() or "/",
        import_layout=import_layout.strip().lower() or "flat",
        watcher_backend=watcher_backend.strip().lower() or "auto",
        scan_concurrency=max(1, int(scan_concurrency)),
        sync_concurrency=max(1, int(sync_concurrency)),
        yandex_token=_strip_optional(yandex_token),
        yandex_client_id=_strip_optional(yandex_client_id),
        yandex_client_secret=_strip_optional(yandex_client_secret),
        nextcloud_url=_normalize_url(_strip_optional(nextcloud_url)),
        nextcloud_username=_strip_optional(nextcloud_username),
        nextcloud_password=_strip_optional(nextcloud_password),
    )


def launch_gui(initial_config: AppConfig, *, manager_name: str = "auto") -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    class CloudBridgeGuiApp:
        def __init__(self) -> None:
            self._root = tk.Tk()
            self._root.title("CloudBridge Setup")
            self._root.geometry("1040x760")
            self._root.minsize(920, 660)
            self._event_queue: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()
            self._busy = False
            self._messagebox = messagebox
            self._filedialog = filedialog
            self._scrolledtext = scrolledtext
            self._ttk = ttk
            self._operation_buttons: list[ttk.Button] = []
            self._auth_url_var = tk.StringVar(value="")
            self._auth_code_var = tk.StringVar(value="")
            self._auth_title_var = tk.StringVar(value="Authorization")
            self._auth_help_var = tk.StringVar(value="Provider login hints will appear here.")

            style = ttk.Style(self._root)
            if "clam" in style.theme_names():
                style.theme_use("clam")
            self._apply_theme(style)

            self._base_config = initial_config
            self._provider_var = tk.StringVar(value=initial_config.provider_name)
            self._sync_root_var = tk.StringVar(value=str(initial_config.sync_root))
            self._import_root_var = tk.StringVar(value=initial_config.import_root)
            self._import_layout_var = tk.StringVar(value=initial_config.import_layout)
            self._watcher_backend_var = tk.StringVar(value=initial_config.watcher_backend)
            self._scan_concurrency_var = tk.IntVar(value=initial_config.scan_concurrency)
            self._sync_concurrency_var = tk.IntVar(value=initial_config.sync_concurrency)
            self._manager_var = tk.StringVar(value=manager_name)
            self._service_name_var = tk.StringVar(value="cloudbridge")
            self._install_filemanager_var = tk.BooleanVar(value=True)
            self._install_service_var = tk.BooleanVar(value=True)

            self._yandex_token_var = tk.StringVar(value=initial_config.yandex_token or "")
            self._yandex_client_id_var = tk.StringVar(value=initial_config.yandex_client_id or "")
            self._yandex_client_secret_var = tk.StringVar(value=initial_config.yandex_client_secret or "")

            self._nextcloud_url_var = tk.StringVar(value=initial_config.nextcloud_url or "")
            self._nextcloud_username_var = tk.StringVar(value=initial_config.nextcloud_username or "")
            self._nextcloud_password_var = tk.StringVar(value=initial_config.nextcloud_password or "")

            self._status_var = tk.StringVar(value=f"Config: {initial_config.resolved_config_path}")

            self._build_ui()
            self._root.after(200, self._pump_events)

        def run(self) -> int:
            self._root.mainloop()
            return 0

        def _build_ui(self) -> None:
            root = self._root
            root.configure(bg=BASEALT_PAPER)
            root.grid_columnconfigure(0, weight=1)
            root.grid_rowconfigure(1, weight=1)

            header = self._ttk.Frame(root, padding=(22, 22, 22, 18), style="Header.TFrame")
            header.grid(row=0, column=0, sticky="nsew")
            header.grid_columnconfigure(0, weight=1)
            self._ttk.Label(
                header,
                text="CloudBridge",
                style="HeroTitle.TLabel",
            ).grid(row=0, column=0, sticky="w")
            self._ttk.Label(
                header,
                text="Linux cloud sync and desktop setup",
                style="HeroSubtitle.TLabel",
            ).grid(row=1, column=0, sticky="w", pady=(6, 0))

            badge = self._ttk.Label(
                header,
                text="BaseALT inspired",
                style="HeroBadge.TLabel",
            )
            badge.grid(row=0, column=1, rowspan=2, sticky="e")

            shell = self._ttk.Frame(root, padding=(18, 12, 18, 12), style="Shell.TFrame")
            shell.grid(row=1, column=0, sticky="nsew")
            shell.grid_columnconfigure(0, weight=3)
            shell.grid_columnconfigure(1, weight=2)
            shell.grid_rowconfigure(0, weight=1)

            notebook = self._ttk.Notebook(shell, style="App.TNotebook")
            notebook.grid(row=0, column=0, sticky="nsew", padx=(0, 14))

            general = self._ttk.Frame(notebook, padding=18, style="Card.TFrame")
            yandex = self._ttk.Frame(notebook, padding=18, style="Card.TFrame")
            nextcloud = self._ttk.Frame(notebook, padding=18, style="Card.TFrame")
            logs = self._ttk.Frame(notebook, padding=18, style="Card.TFrame")
            for frame in (general, yandex, nextcloud, logs):
                frame.grid_columnconfigure(1, weight=1)

            notebook.add(general, text="General")
            notebook.add(yandex, text="Yandex")
            notebook.add(nextcloud, text="Nextcloud")
            notebook.add(logs, text="Log")

            self._build_general_tab(general)
            self._build_yandex_tab(yandex)
            self._build_nextcloud_tab(nextcloud)
            self._build_log_tab(logs)

            side = self._ttk.Frame(shell, padding=(0, 0, 0, 0), style="Shell.TFrame")
            side.grid(row=0, column=1, sticky="nsew")
            side.grid_rowconfigure(1, weight=1)
            side.grid_columnconfigure(0, weight=1)
            self._build_auth_panel(side)
            self._build_quick_help_panel(side)

            footer = self._ttk.Frame(root, padding=(18, 6, 18, 18), style="Shell.TFrame")
            footer.grid(row=2, column=0, sticky="ew")
            footer.grid_columnconfigure(0, weight=1)
            self._ttk.Label(footer, textvariable=self._status_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")

        def _build_general_tab(self, frame) -> None:
            self._add_row(frame, 0, "Provider", self._combo(frame, self._provider_var, ("yandex", "nextcloud")))

            sync_root_row = self._ttk.Frame(frame)
            sync_root_row.grid_columnconfigure(0, weight=1)
            sync_root_entry = self._ttk.Entry(sync_root_row, textvariable=self._sync_root_var)
            sync_root_entry.grid(row=0, column=0, sticky="ew")
            browse_button = self._ttk.Button(sync_root_row, text="Browse", command=self._choose_sync_root)
            browse_button.grid(row=0, column=1, padx=(8, 0))
            self._add_row(frame, 1, "Sync root", sync_root_row)

            self._add_row(frame, 2, "Import root", self._ttk.Entry(frame, textvariable=self._import_root_var))
            self._add_row(frame, 3, "Import layout", self._combo(frame, self._import_layout_var, ("flat", "by-parent", "by-date")))
            self._add_row(frame, 4, "Watcher backend", self._combo(frame, self._watcher_backend_var, ("auto", "watchdog", "poll")))
            self._add_row(frame, 5, "Scan concurrency", self._spinbox(frame, self._scan_concurrency_var, 1, 64))
            self._add_row(frame, 6, "Sync concurrency", self._spinbox(frame, self._sync_concurrency_var, 1, 64))
            self._add_row(frame, 7, "File manager", self._combo(frame, self._manager_var, ("auto", "nautilus", "thunar", "nemo", "caja")))
            self._add_row(frame, 8, "Service name", self._ttk.Entry(frame, textvariable=self._service_name_var))

            options = self._ttk.LabelFrame(frame, text="Desktop setup", padding=12)
            options.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(16, 0))
            options.grid_columnconfigure(0, weight=1)
            self._ttk.Checkbutton(
                options,
                text="Install file-manager integration",
                variable=self._install_filemanager_var,
            ).grid(row=0, column=0, sticky="w")
            self._ttk.Checkbutton(
                options,
                text="Install systemd user service",
                variable=self._install_service_var,
            ).grid(row=1, column=0, sticky="w", pady=(6, 0))

            actions = self._ttk.Frame(frame)
            actions.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(20, 0))
            actions.grid_columnconfigure(0, weight=1)
            save_button = self._ttk.Button(actions, text="Save config", style="Secondary.TButton", command=self._save_config)
            save_button.grid(row=0, column=0, sticky="w")
            setup_button = self._ttk.Button(actions, text="Run desktop setup", style="Primary.TButton", command=self._run_desktop_setup)
            setup_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
            self._operation_buttons.extend([save_button, setup_button, browse_button])

        def _build_yandex_tab(self, frame) -> None:
            self._add_row(frame, 0, "Access token", self._ttk.Entry(frame, textvariable=self._yandex_token_var, show="*"))
            self._add_row(frame, 1, "Client ID", self._ttk.Entry(frame, textvariable=self._yandex_client_id_var))
            self._add_row(frame, 2, "Client secret", self._ttk.Entry(frame, textvariable=self._yandex_client_secret_var, show="*"))

            actions = self._ttk.Frame(frame)
            actions.grid(row=3, column=0, columnspan=2, sticky="w", pady=(20, 0))
            login_button = self._ttk.Button(actions, text="Start device login", style="Primary.TButton", command=self._run_yandex_login)
            login_button.grid(row=0, column=0, sticky="w")
            self._operation_buttons.append(login_button)

            self._ttk.Label(
                frame,
                text="Use the code shown in the authorization panel. Yandex does not send it by email or SMS.",
                style="Muted.TLabel",
                wraplength=540,
                justify="left",
            ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(16, 0))

        def _build_nextcloud_tab(self, frame) -> None:
            self._add_row(frame, 0, "Server URL", self._ttk.Entry(frame, textvariable=self._nextcloud_url_var))
            self._add_row(frame, 1, "Username", self._ttk.Entry(frame, textvariable=self._nextcloud_username_var))
            self._add_row(frame, 2, "App password", self._ttk.Entry(frame, textvariable=self._nextcloud_password_var, show="*"))

            actions = self._ttk.Frame(frame)
            actions.grid(row=3, column=0, columnspan=2, sticky="w", pady=(20, 0))
            login_button = self._ttk.Button(actions, text="Start browser login", style="Primary.TButton", command=self._run_nextcloud_login)
            login_button.grid(row=0, column=0, sticky="w")
            self._operation_buttons.append(login_button)

            self._ttk.Label(
                frame,
                text="The login URL will appear in the authorization panel and in the log.",
                style="Muted.TLabel",
                wraplength=540,
                justify="left",
            ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(16, 0))

        def _build_log_tab(self, frame) -> None:
            frame.grid_rowconfigure(0, weight=1)
            frame.grid_columnconfigure(0, weight=1)
            self._log_widget = self._scrolledtext.ScrolledText(
                frame,
                state="disabled",
                wrap="word",
                bg=BASEALT_GRAPHITE,
                fg=BASEALT_PAPER,
                insertbackground=BASEALT_PAPER,
                relief="flat",
                borderwidth=0,
                padx=12,
                pady=12,
            )
            self._log_widget.grid(row=0, column=0, sticky="nsew")

        def _build_auth_panel(self, frame) -> None:
            panel = self._ttk.Frame(frame, padding=18, style="Card.TFrame")
            panel.grid(row=0, column=0, sticky="new")
            panel.grid_columnconfigure(0, weight=1)

            self._ttk.Label(panel, textvariable=self._auth_title_var, style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
            self._ttk.Label(
                panel,
                textvariable=self._auth_help_var,
                style="Muted.TLabel",
                wraplength=300,
                justify="left",
            ).grid(row=1, column=0, sticky="w", pady=(8, 14))

            self._ttk.Label(panel, text="Verification URL", style="FieldLabel.TLabel").grid(row=2, column=0, sticky="w")
            url_row = self._ttk.Frame(panel, style="Card.TFrame")
            url_row.grid(row=3, column=0, sticky="ew", pady=(6, 12))
            url_row.grid_columnconfigure(0, weight=1)
            self._auth_url_entry = self._ttk.Entry(url_row, textvariable=self._auth_url_var, state="readonly")
            self._auth_url_entry.grid(row=0, column=0, sticky="ew")
            open_button = self._ttk.Button(url_row, text="Open", style="Secondary.TButton", command=self._open_auth_url)
            open_button.grid(row=0, column=1, padx=(8, 0))
            copy_url_button = self._ttk.Button(url_row, text="Copy URL", style="Secondary.TButton", command=self._copy_auth_url)
            copy_url_button.grid(row=0, column=2, padx=(8, 0))

            self._ttk.Label(panel, text="Device code", style="FieldLabel.TLabel").grid(row=4, column=0, sticky="w")
            code_row = self._ttk.Frame(panel, style="Card.TFrame")
            code_row.grid(row=5, column=0, sticky="ew", pady=(6, 0))
            code_row.grid_columnconfigure(0, weight=1)
            self._auth_code_entry = self._ttk.Entry(code_row, textvariable=self._auth_code_var, state="readonly")
            self._auth_code_entry.grid(row=0, column=0, sticky="ew")
            copy_code_button = self._ttk.Button(code_row, text="Copy code", style="Primary.TButton", command=self._copy_auth_code)
            copy_code_button.grid(row=0, column=1, padx=(8, 0))

            self._operation_buttons.extend([open_button, copy_url_button, copy_code_button])

        def _build_quick_help_panel(self, frame) -> None:
            panel = self._ttk.Frame(frame, padding=18, style="CardAlt.TFrame")
            panel.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
            panel.grid_columnconfigure(0, weight=1)
            self._ttk.Label(panel, text="Quick flow", style="SectionTitleInverse.TLabel").grid(row=0, column=0, sticky="w")
            self._ttk.Label(
                panel,
                text=(
                    "1. Choose a provider and save config.\n"
                    "2. Start Yandex or Nextcloud login.\n"
                    "3. Use the URL and code from the panel on the right.\n"
                    "4. Run desktop setup to install the file-manager hooks and service."
                ),
                style="MutedInverse.TLabel",
                wraplength=300,
                justify="left",
            ).grid(row=1, column=0, sticky="w", pady=(10, 0))

        def _apply_theme(self, style) -> None:
            style.configure(".", font=("Segoe UI", 10))
            style.configure("Shell.TFrame", background=BASEALT_PAPER)
            style.configure("Header.TFrame", background=BASEALT_GRAPHITE)
            style.configure("Card.TFrame", background=BASEALT_PANEL, relief="flat")
            style.configure("CardAlt.TFrame", background=BASEALT_GRAPHITE, relief="flat")
            style.configure("TLabel", background=BASEALT_PANEL, foreground=BASEALT_TEXT)
            style.configure("HeroTitle.TLabel", background=BASEALT_GRAPHITE, foreground=BASEALT_PAPER, font=("Segoe UI", 24, "bold"))
            style.configure("HeroSubtitle.TLabel", background=BASEALT_GRAPHITE, foreground="#E7DED6", font=("Segoe UI", 11))
            style.configure(
                "HeroBadge.TLabel",
                background=BASEALT_RED,
                foreground="#FFFFFF",
                font=("Segoe UI", 10, "bold"),
                padding=(14, 8),
            )
            style.configure("SectionTitle.TLabel", background=BASEALT_PANEL, foreground=BASEALT_TEXT, font=("Segoe UI", 12, "bold"))
            style.configure("SectionTitleInverse.TLabel", background=BASEALT_GRAPHITE, foreground=BASEALT_PAPER, font=("Segoe UI", 12, "bold"))
            style.configure("Muted.TLabel", background=BASEALT_PANEL, foreground=BASEALT_MUTED, font=("Segoe UI", 10))
            style.configure("MutedInverse.TLabel", background=BASEALT_GRAPHITE, foreground="#D7CEC7", font=("Segoe UI", 10))
            style.configure("FieldLabel.TLabel", background=BASEALT_PANEL, foreground=BASEALT_MUTED, font=("Segoe UI", 9, "bold"))
            style.configure("Status.TLabel", background=BASEALT_PAPER, foreground=BASEALT_MUTED)
            style.configure("TLabelframe", background=BASEALT_PANEL, borderwidth=1, relief="solid")
            style.configure("TLabelframe.Label", background=BASEALT_PANEL, foreground=BASEALT_TEXT, font=("Segoe UI", 10, "bold"))
            style.configure(
                "TNotebook",
                background=BASEALT_PAPER,
                borderwidth=0,
                tabmargins=(0, 0, 0, 0),
            )
            style.configure(
                "TNotebook.Tab",
                background="#E7DBD0",
                foreground=BASEALT_TEXT,
                padding=(16, 10),
                font=("Segoe UI", 10, "bold"),
            )
            style.map(
                "TNotebook.Tab",
                background=[("selected", BASEALT_RED), ("active", "#EED5D7")],
                foreground=[("selected", "#FFFFFF"), ("active", BASEALT_TEXT)],
            )
            style.configure("TEntry", fieldbackground="#FFFFFF", foreground=BASEALT_TEXT, padding=7)
            style.configure("TCombobox", fieldbackground="#FFFFFF", foreground=BASEALT_TEXT, padding=7)
            style.configure("TSpinbox", fieldbackground="#FFFFFF", foreground=BASEALT_TEXT)
            style.configure("Primary.TButton", background=BASEALT_RED, foreground="#FFFFFF", borderwidth=0, padding=(14, 9), font=("Segoe UI", 10, "bold"))
            style.map("Primary.TButton", background=[("active", BASEALT_RED_DARK), ("disabled", "#C7B8AF")], foreground=[("disabled", "#F8F2ED")])
            style.configure("Secondary.TButton", background="#E8DDD4", foreground=BASEALT_TEXT, borderwidth=0, padding=(12, 9), font=("Segoe UI", 10, "bold"))
            style.map("Secondary.TButton", background=[("active", "#DACBBF"), ("disabled", "#EEE6DF")], foreground=[("disabled", "#A3948B")])
            style.configure("TCheckbutton", background=BASEALT_PANEL, foreground=BASEALT_TEXT)

        def _add_row(self, frame, row: int, label: str, widget) -> None:
            self._ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)
            widget.grid(row=row, column=1, sticky="ew", pady=6)

        def _combo(self, frame, variable, values: tuple[str, ...]):
            combo = self._ttk.Combobox(frame, textvariable=variable, values=values, state="readonly")
            return combo

        def _spinbox(self, frame, variable, minimum: int, maximum: int):
            return self._ttk.Spinbox(frame, from_=minimum, to=maximum, textvariable=variable, increment=1)

        def _choose_sync_root(self) -> None:
            selected = self._filedialog.askdirectory(initialdir=self._sync_root_var.get() or str(Path.home()))
            if selected:
                self._sync_root_var.set(selected)

        def _set_auth_prompt(self, *, title: str, url: str, code: str, help_text: str) -> None:
            self._auth_title_var.set(title)
            self._auth_url_var.set(url)
            self._auth_code_var.set(code)
            self._auth_help_var.set(help_text)
            if url:
                print(f"auth_url={url}", flush=True)
            if code:
                print(f"auth_code={code}", flush=True)

        def _open_auth_url(self) -> None:
            url = self._auth_url_var.get().strip()
            if not url:
                return
            try:
                webbrowser.open(url)
            except Exception as error:
                self._messagebox.showerror("CloudBridge", f"Failed to open browser:\n{error}")

        def _copy_auth_url(self) -> None:
            url = self._auth_url_var.get().strip()
            if not url:
                return
            if copy_text_to_clipboard(url):
                self._status_var.set("Authorization URL copied to clipboard")

        def _copy_auth_code(self) -> None:
            code = self._auth_code_var.get().strip()
            if not code:
                return
            if copy_text_to_clipboard(code):
                self._status_var.set("Authorization code copied to clipboard")

        def _current_config(self) -> AppConfig:
            return build_gui_config(
                self._base_config,
                provider_name=self._provider_var.get(),
                sync_root=self._sync_root_var.get(),
                import_root=self._import_root_var.get(),
                import_layout=self._import_layout_var.get(),
                watcher_backend=self._watcher_backend_var.get(),
                scan_concurrency=self._scan_concurrency_var.get(),
                sync_concurrency=self._sync_concurrency_var.get(),
                yandex_token=self._yandex_token_var.get(),
                yandex_client_id=self._yandex_client_id_var.get(),
                yandex_client_secret=self._yandex_client_secret_var.get(),
                nextcloud_url=self._nextcloud_url_var.get(),
                nextcloud_username=self._nextcloud_username_var.get(),
                nextcloud_password=self._nextcloud_password_var.get(),
            )

        def _save_config(self, *, notify: bool = True) -> None:
            try:
                config = self._current_config()
                path = config.write_persisted_settings()
                self._base_config = config
                self._status_var.set(f"Config saved: {path}")
                self._log(f"Saved config: {path}")
                if notify:
                    self._messagebox.showinfo("CloudBridge", f"Config saved to:\n{path}")
            except Exception as error:
                self._messagebox.showerror("CloudBridge", str(error))
                self._log(f"Save failed: {error}")

        def _run_yandex_login(self) -> None:
            client_id = self._yandex_client_id_var.get().strip()
            client_secret = self._yandex_client_secret_var.get().strip()
            if not client_id or not client_secret:
                self._messagebox.showerror("CloudBridge", "Yandex device login requires Client ID and Client secret.")
                return

            def worker() -> dict[str, str]:
                async def job() -> dict[str, str]:
                    def on_ready(prompt) -> None:
                        self._event_queue.put(("log", f"Yandex verification URL: {prompt.verification_url}"))
                        self._event_queue.put(("log", f"Yandex user code: {prompt.user_code}"))
                        self._event_queue.put(("yandex-prompt", (prompt.verification_url, prompt.user_code)))

                    result = await run_yandex_device_login_flow(
                        client_id,
                        client_secret,
                        on_ready=on_ready,
                    )
                    provider = YandexDiskProvider(result.access_token)
                    try:
                        if await provider.stat("/") is None:
                            raise RuntimeError("Yandex login succeeded, but the Disk root is not accessible.")
                    finally:
                        await provider.close()
                    return {
                        "token": result.access_token,
                        "client_id": client_id,
                        "client_secret": client_secret,
                    }

                return asyncio.run(job())

            self._start_worker("Yandex login", worker, self._complete_yandex_login)

        def _complete_yandex_login(self, payload: dict[str, str]) -> None:
            self._provider_var.set("yandex")
            self._yandex_token_var.set(payload["token"])
            self._yandex_client_id_var.set(payload["client_id"])
            self._yandex_client_secret_var.set(payload["client_secret"])
            self._save_config(notify=False)
            self._messagebox.showinfo("CloudBridge", "Yandex login completed.")

        def _run_nextcloud_login(self) -> None:
            server = self._nextcloud_url_var.get().strip()
            if not server:
                self._messagebox.showerror("CloudBridge", "Nextcloud browser login requires Server URL.")
                return

            def worker() -> dict[str, str]:
                async def job() -> dict[str, str]:
                    def on_ready(prompt) -> None:
                        self._event_queue.put(("log", f"Nextcloud login URL: {prompt.login_url}"))
                        self._event_queue.put(("nextcloud-prompt", prompt.login_url))

                    result = await run_nextcloud_login_flow(server, on_ready=on_ready)
                    provider = NextcloudProvider(result.server_url, result.login_name, result.app_password)
                    try:
                        if await provider.stat("/") is None:
                            raise RuntimeError("Nextcloud login succeeded, but the WebDAV root is not accessible.")
                    finally:
                        await provider.close()
                    return {
                        "server": result.server_url,
                        "username": result.login_name,
                        "password": result.app_password,
                    }

                return asyncio.run(job())

            self._start_worker("Nextcloud login", worker, self._complete_nextcloud_login)

        def _complete_nextcloud_login(self, payload: dict[str, str]) -> None:
            self._provider_var.set("nextcloud")
            self._nextcloud_url_var.set(payload["server"])
            self._nextcloud_username_var.set(payload["username"])
            self._nextcloud_password_var.set(payload["password"])
            self._save_config(notify=False)
            self._messagebox.showinfo("CloudBridge", "Nextcloud login completed.")

        def _run_desktop_setup(self) -> None:
            try:
                config = self._current_config()
                config.write_persisted_settings()
                self._base_config = config
            except Exception as error:
                self._messagebox.showerror("CloudBridge", str(error))
                return

            manager_name = self._manager_var.get()
            install_filemanager = bool(self._install_filemanager_var.get())
            install_service = bool(self._install_service_var.get())
            service_name = self._service_name_var.get().strip() or "cloudbridge"
            launcher_command = default_gui_launcher_command()

            def worker() -> list[str]:
                async def bootstrap() -> None:
                    manager = await HybridManager.from_config(config)
                    try:
                        await manager.bootstrap()
                    finally:
                        await manager.close()

                asyncio.run(bootstrap())
                messages = [f"Database initialized: {config.database_path}"]

                if install_filemanager:
                    resolved_manager = manager_name
                    if resolved_manager == "auto":
                        detected = detect_file_manager()
                        if detected is None:
                            raise RuntimeError("Could not detect a supported file manager.")
                        resolved_manager = detected
                    if resolved_manager == "nautilus":
                        result = install_nautilus_integration(config, repo_root=None, launcher_command=launcher_command)
                        messages.append(f"Nautilus extension: {result.extension_path}")
                    elif resolved_manager == "thunar":
                        result = install_thunar_integration(config, repo_root=None, launcher_command=launcher_command)
                        messages.append(f"Thunar UCA config: {result.config_path}")
                    elif resolved_manager == "nemo":
                        result = install_nemo_integration(config, repo_root=None, launcher_command=launcher_command)
                        messages.append("Nemo actions: " + ", ".join(str(path) for path in result.action_paths))
                    else:
                        result = install_caja_integration(config, repo_root=None, launcher_command=launcher_command)
                        messages.append(f"Caja extension: {result.extension_path}")
                        messages.append("Caja actions: " + ", ".join(str(path) for path in result.action_paths))

                if install_service:
                    result = install_systemd_user_service(
                        config,
                        repo_root=None,
                        launcher_command=launcher_command,
                        service_name=service_name,
                    )
                    messages.append(f"systemd unit: {result.unit_path}")
                    if shutil.which("systemctl"):
                        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
                        subprocess.run(["systemctl", "--user", "enable", "--now", f"{service_name}.service"], check=False)
                        messages.append(f"systemd service requested: {service_name}.service")

                return messages

            self._start_worker("Desktop setup", worker, self._complete_desktop_setup)

        def _complete_desktop_setup(self, messages: list[str]) -> None:
            for message in messages:
                self._log(message)
            self._messagebox.showinfo("CloudBridge", "Desktop setup completed.")

        def _start_worker(
            self,
            label: str,
            worker: Callable[[], object],
            success_callback: Callable[[object], None],
        ) -> None:
            if self._busy:
                self._messagebox.showwarning("CloudBridge", "Another operation is already running.")
                return
            self._set_busy(True)
            self._log(f"{label} started")

            def runner() -> None:
                try:
                    result = worker()
                except Exception as error:
                    self._event_queue.put(("error", (label, error)))
                else:
                    self._event_queue.put(("success", (label, success_callback, result)))

            threading.Thread(target=runner, daemon=True).start()

        def _pump_events(self) -> None:
            while True:
                try:
                    event_type, payload = self._event_queue.get_nowait()
                except queue.Empty:
                    break
                if event_type == "log":
                    self._log(str(payload))
                    continue
                if event_type == "error":
                    label, error = payload  # type: ignore[misc]
                    self._set_busy(False)
                    self._log(f"{label} failed: {error}")
                    self._messagebox.showerror("CloudBridge", f"{label} failed:\n{error}")
                    continue
                if event_type == "yandex-prompt":
                    verification_url, user_code = payload  # type: ignore[misc]
                    self._set_auth_prompt(
                        title="Yandex device login",
                        url=verification_url,
                        code=user_code,
                        help_text="Open the URL, then enter the code shown here. Yandex does not send this code by email or SMS.",
                    )
                    self._status_var.set("Yandex device code is ready")
                    self._messagebox.showinfo(
                        "CloudBridge Yandex Login",
                        "Open the verification URL and enter the code from the authorization panel.",
                    )
                    continue
                if event_type == "nextcloud-prompt":
                    login_url = payload  # type: ignore[assignment]
                    self._set_auth_prompt(
                        title="Nextcloud browser login",
                        url=login_url,
                        code="",
                        help_text="Open the URL and complete the login in your browser. No separate code is required.",
                    )
                    self._status_var.set("Nextcloud login URL is ready")
                    self._messagebox.showinfo(
                        "CloudBridge Nextcloud Login",
                        "Open the URL from the authorization panel and complete the login in your browser.",
                    )
                    continue
                if event_type == "success":
                    label, callback, result = payload  # type: ignore[misc]
                    self._set_busy(False)
                    self._log(f"{label} completed")
                    callback(result)
            self._root.after(200, self._pump_events)

        def _set_busy(self, busy: bool) -> None:
            self._busy = busy
            state = "disabled" if busy else "normal"
            for button in self._operation_buttons:
                button.configure(state=state)
            self._status_var.set("Working..." if busy else f"Config: {self._base_config.resolved_config_path}")

        def _log(self, message: str) -> None:
            self._log_widget.configure(state="normal")
            self._log_widget.insert("end", message.rstrip() + "\n")
            self._log_widget.see("end")
            self._log_widget.configure(state="disabled")

    return CloudBridgeGuiApp().run()


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _normalize_url(value: str | None) -> str | None:
    if value is None:
        return None
    return value.rstrip("/")
