from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class AppConfig:
    app_home: Path
    sync_root: Path
    database_path: Path
    provider_name: str
    yandex_token: str | None
    scan_concurrency: int = 8
    sync_concurrency: int = 4

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "AppConfig":
        source = env or os.environ
        app_home = Path(source.get("CLOUDBRIDGE_HOME", Path.home() / ".local" / "share" / "cloudbridge")).expanduser()
        sync_root = Path(source.get("CLOUDBRIDGE_SYNC_ROOT", app_home / "mirror")).expanduser()
        database_path = Path(source.get("CLOUDBRIDGE_DATABASE", app_home / "state.db")).expanduser()
        provider_name = source.get("CLOUDBRIDGE_PROVIDER", "yandex").strip().lower()
        yandex_token = source.get("YANDEX_DISK_TOKEN")
        scan_concurrency = max(1, int(source.get("CLOUDBRIDGE_SCAN_CONCURRENCY", "8")))
        sync_concurrency = max(1, int(source.get("CLOUDBRIDGE_SYNC_CONCURRENCY", "4")))
        return cls(
            app_home=app_home,
            sync_root=sync_root,
            database_path=database_path,
            provider_name=provider_name,
            yandex_token=yandex_token,
            scan_concurrency=scan_concurrency,
            sync_concurrency=sync_concurrency,
        )

    def ensure_directories(self) -> None:
        self.app_home.mkdir(parents=True, exist_ok=True)
        self.sync_root.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
