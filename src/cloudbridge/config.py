from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class AppConfig:
    app_home: Path
    sync_root: Path
    database_path: Path
    provider_name: str
    yandex_token: str | None
    yandex_client_id: str | None = None
    yandex_client_secret: str | None = None
    nextcloud_url: str | None = None
    nextcloud_username: str | None = None
    nextcloud_password: str | None = None
    config_path: Path | None = None
    import_root: str = "/"
    import_layout: str = "flat"
    watcher_backend: str = "auto"
    scan_concurrency: int = 8
    sync_concurrency: int = 4

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "AppConfig":
        source = env or os.environ
        app_home = Path(source.get("CLOUDBRIDGE_HOME", Path.home() / ".local" / "share" / "cloudbridge")).expanduser()
        config_path = Path(source.get("CLOUDBRIDGE_CONFIG", app_home / "config.json")).expanduser()
        persisted = _load_persisted_settings(config_path)
        sync_root = Path(_get_setting(source, persisted, "CLOUDBRIDGE_SYNC_ROOT", app_home / "mirror")).expanduser()
        database_path = Path(_get_setting(source, persisted, "CLOUDBRIDGE_DATABASE", app_home / "state.db")).expanduser()
        provider_name = str(_get_setting(source, persisted, "CLOUDBRIDGE_PROVIDER", "yandex")).strip().lower()
        yandex_token = _optional_string(_get_setting(source, persisted, "YANDEX_DISK_TOKEN"))
        yandex_client_id = _optional_string(_get_setting(source, persisted, "YANDEX_CLIENT_ID"))
        yandex_client_secret = _optional_string(_get_setting(source, persisted, "YANDEX_CLIENT_SECRET"))
        nextcloud_url = _normalize_base_url(_optional_string(_get_setting(source, persisted, "NEXTCLOUD_URL")))
        nextcloud_username = _optional_string(_get_setting(source, persisted, "NEXTCLOUD_USERNAME"))
        nextcloud_password = _optional_string(_get_setting(source, persisted, "NEXTCLOUD_PASSWORD"))
        import_root = str(_get_setting(source, persisted, "CLOUDBRIDGE_IMPORT_ROOT", "/")).strip() or "/"
        import_layout = str(_get_setting(source, persisted, "CLOUDBRIDGE_IMPORT_LAYOUT", "flat")).strip().lower() or "flat"
        watcher_backend = str(_get_setting(source, persisted, "CLOUDBRIDGE_WATCHER_BACKEND", "auto")).strip().lower() or "auto"
        scan_concurrency = max(1, int(_get_setting(source, persisted, "CLOUDBRIDGE_SCAN_CONCURRENCY", "8")))
        sync_concurrency = max(1, int(_get_setting(source, persisted, "CLOUDBRIDGE_SYNC_CONCURRENCY", "4")))
        if import_layout not in {"flat", "by-parent", "by-date"}:
            raise ValueError(f"Unsupported import layout: {import_layout}")
        if watcher_backend not in {"auto", "poll", "watchdog"}:
            raise ValueError(f"Unsupported watcher backend: {watcher_backend}")
        return cls(
            app_home=app_home,
            sync_root=sync_root,
            database_path=database_path,
            provider_name=provider_name,
            yandex_token=yandex_token,
            yandex_client_id=yandex_client_id,
            yandex_client_secret=yandex_client_secret,
            nextcloud_url=nextcloud_url,
            nextcloud_username=nextcloud_username,
            nextcloud_password=nextcloud_password,
            config_path=config_path,
            import_root=import_root,
            import_layout=import_layout,
            watcher_backend=watcher_backend,
            scan_concurrency=scan_concurrency,
            sync_concurrency=sync_concurrency,
        )

    def ensure_directories(self) -> None:
        self.app_home.mkdir(parents=True, exist_ok=True)
        self.sync_root.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.resolved_config_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def resolved_config_path(self) -> Path:
        return (self.config_path or (self.app_home / "config.json")).expanduser()

    def to_persisted_settings(self) -> dict[str, str]:
        settings = {
            "CLOUDBRIDGE_HOME": str(self.app_home),
            "CLOUDBRIDGE_SYNC_ROOT": str(self.sync_root),
            "CLOUDBRIDGE_DATABASE": str(self.database_path),
            "CLOUDBRIDGE_PROVIDER": self.provider_name,
            "CLOUDBRIDGE_IMPORT_ROOT": self.import_root,
            "CLOUDBRIDGE_IMPORT_LAYOUT": self.import_layout,
            "CLOUDBRIDGE_WATCHER_BACKEND": self.watcher_backend,
            "CLOUDBRIDGE_SCAN_CONCURRENCY": str(self.scan_concurrency),
            "CLOUDBRIDGE_SYNC_CONCURRENCY": str(self.sync_concurrency),
        }
        if self.yandex_token:
            settings["YANDEX_DISK_TOKEN"] = self.yandex_token
        if self.yandex_client_id:
            settings["YANDEX_CLIENT_ID"] = self.yandex_client_id
        if self.yandex_client_secret:
            settings["YANDEX_CLIENT_SECRET"] = self.yandex_client_secret
        if self.nextcloud_url:
            settings["NEXTCLOUD_URL"] = self.nextcloud_url
        if self.nextcloud_username:
            settings["NEXTCLOUD_USERNAME"] = self.nextcloud_username
        if self.nextcloud_password:
            settings["NEXTCLOUD_PASSWORD"] = self.nextcloud_password
        return settings

    def write_persisted_settings(self) -> Path:
        self.ensure_directories()
        config_path = self.resolved_config_path
        config_path.write_text(
            json.dumps(self.to_persisted_settings(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            config_path.chmod(0o600)
        except OSError:
            pass
        return config_path


def _get_setting(source: dict[str, str], persisted: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in source:
        return source[key]
    return persisted.get(key, default)


def _load_persisted_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Persisted config must be a JSON object: {path}")
    return payload


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_base_url(value: str | None) -> str | None:
    if not value:
        return None
    return value.rstrip("/")
