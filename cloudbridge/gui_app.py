from __future__ import annotations

import asyncio
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .config import Settings, load_settings
from .state_db import StateDB


class CloudBridgeApp:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._root = tk.Tk()
        self._root.title("CloudBridge")
        self._root.geometry("980x620")
        self._busy = False

        self._status_var = tk.StringVar(
            value=f"Ready. Local root: {self._settings.local_root}"
        )

        self._build_ui()
        self._refresh_rows()

    def run(self) -> None:
        self._root.mainloop()

    def _build_ui(self) -> None:
        top = ttk.Frame(self._root, padding=12)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Provider:").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(top, text=self._settings.provider_type).grid(row=0, column=1, sticky=tk.W, padx=(6, 18))
        ttk.Label(top, text="Local Root:").grid(row=0, column=2, sticky=tk.W)
        ttk.Label(top, text=str(self._settings.local_root)).grid(row=0, column=3, sticky=tk.W, padx=(6, 0))
        ttk.Label(top, text="Cloud Root:").grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Label(top, text=self._settings.cloud_root).grid(row=1, column=1, sticky=tk.W, padx=(6, 18), pady=(8, 0))
        ttk.Label(top, text="DB:").grid(row=1, column=2, sticky=tk.W, pady=(8, 0))
        ttk.Label(top, text=str(self._settings.db_path)).grid(row=1, column=3, sticky=tk.W, padx=(6, 0), pady=(8, 0))

        buttons = ttk.Frame(self._root, padding=(12, 0, 12, 12))
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Init DB", command=lambda: self._run_action("Initializing DB", self._init_db)).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Discover", command=lambda: self._run_action("Discovering remote files", self._discover)).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Sync", command=lambda: self._run_action("Synchronizing", self._sync)).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Refresh", command=self._refresh_rows).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Open Folder", command=self._open_local_root).pack(side=tk.LEFT, padx=(8, 0))

        columns = ("path", "status", "cloud", "local", "placeholder", "size")
        self._tree = ttk.Treeview(self._root, columns=columns, show="headings")
        self._tree.heading("path", text="Path")
        self._tree.heading("status", text="Status")
        self._tree.heading("cloud", text="Cloud")
        self._tree.heading("local", text="Local")
        self._tree.heading("placeholder", text="Placeholder")
        self._tree.heading("size", text="Cloud Size")
        self._tree.column("path", width=430, anchor=tk.W)
        self._tree.column("status", width=120, anchor=tk.W)
        self._tree.column("cloud", width=80, anchor=tk.CENTER)
        self._tree.column("local", width=80, anchor=tk.CENTER)
        self._tree.column("placeholder", width=100, anchor=tk.CENTER)
        self._tree.column("size", width=120, anchor=tk.E)

        scroll = ttk.Scrollbar(self._root, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0), pady=(0, 12))
        scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12), pady=(0, 12))

        status = ttk.Label(self._root, textvariable=self._status_var, padding=(12, 0, 12, 12))
        status.pack(fill=tk.X)

    def _run_action(self, label: str, action) -> None:
        if self._busy:
            return
        self._busy = True
        self._status_var.set(label)

        def runner() -> None:
            try:
                result = self._run_coro_sync(action())
            except Exception as exc:  # pragma: no cover - defensive GUI path
                message = f"Error: {exc}"
                self._root.after(
                    0,
                    lambda msg=message: self._finish_action(msg, show_error=True),
                )
                return
            self._root.after(0, lambda: self._finish_action(result or "Done"))

        threading.Thread(target=runner, daemon=True).start()

    def _finish_action(self, message: str, *, show_error: bool = False) -> None:
        self._busy = False
        self._status_var.set(message)
        self._refresh_rows()
        if show_error:
            messagebox.showerror("CloudBridge", message)

    def _refresh_rows(self) -> None:
        try:
            rows = self._run_coro_sync(self._load_rows())
        except Exception as exc:  # pragma: no cover - defensive GUI path
            self._status_var.set(f"Failed to load state: {exc}")
            return

        for item in self._tree.get_children():
            self._tree.delete(item)

        for row in rows:
            local_label = "yes" if row["local_exists"] else "no"
            cloud_label = "yes" if row["cloud_exists"] else "no"
            placeholder_label = "yes" if row["placeholder"] else "no"
            size = row["size"] if row["size"] is not None else ""
            self._tree.insert(
                "",
                tk.END,
                values=(
                    row["path"],
                    row["status"],
                    cloud_label,
                    local_label,
                    placeholder_label,
                    size,
                ),
            )

    async def _load_rows(self) -> list[dict]:
        db = StateDB(self._settings.db_path)
        await db.connect()
        try:
            await db.init_schema()
            return await db.list_all(include_deleted=False)
        finally:
            await db.close()

    async def _init_db(self) -> str:
        from .__main__ import run_init_db

        await run_init_db(self._settings)
        return f"Initialized DB at {self._settings.db_path}"

    async def _discover(self) -> str:
        from .__main__ import run_discover

        code = await run_discover(self._settings, recursive=True)
        return "Discover completed" if code == 0 else f"Discover failed with code {code}"

    async def _sync(self) -> str:
        from .__main__ import run_sync

        code = await run_sync(self._settings)
        return "Sync completed" if code == 0 else f"Sync finished with code {code}"

    def _open_local_root(self) -> None:
        try:
            subprocess.Popen(["xdg-open", str(self._settings.local_root)])
        except OSError as exc:  # pragma: no cover - desktop dependent
            messagebox.showerror("CloudBridge", f"Failed to open folder: {exc}")

    @staticmethod
    def _run_coro_sync(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def launch_gui(settings: Settings | None = None) -> None:
    app = CloudBridgeApp(settings or load_settings())
    app.run()
