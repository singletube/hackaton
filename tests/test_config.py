from __future__ import annotations

import json
from pathlib import Path

from cloudbridge.config import AppConfig


def test_from_env_loads_persisted_nextcloud_settings(tmp_path: Path) -> None:
    app_home = tmp_path / "app"
    app_home.mkdir(parents=True)
    config_path = app_home / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "CLOUDBRIDGE_PROVIDER": "nextcloud",
                "NEXTCLOUD_URL": "https://cloud.example.test/",
                "NEXTCLOUD_USERNAME": "alice",
                "NEXTCLOUD_PASSWORD": "secret",
                "CLOUDBRIDGE_IMPORT_ROOT": "/incoming",
            }
        ),
        encoding="utf-8",
    )

    config = AppConfig.from_env({"CLOUDBRIDGE_HOME": str(app_home)})

    assert config.provider_name == "nextcloud"
    assert config.nextcloud_url == "https://cloud.example.test"
    assert config.nextcloud_username == "alice"
    assert config.nextcloud_password == "secret"
    assert config.import_root == "/incoming"
    assert config.resolved_config_path == config_path


def test_write_persisted_settings_serializes_provider_credentials(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="nextcloud",
        yandex_token=None,
        nextcloud_url="https://cloud.example.test",
        nextcloud_username="alice",
        nextcloud_password="secret",
    )

    config_path = config.write_persisted_settings()
    payload = json.loads(config_path.read_text(encoding="utf-8"))

    assert payload["CLOUDBRIDGE_PROVIDER"] == "nextcloud"
    assert payload["NEXTCLOUD_URL"] == "https://cloud.example.test"
    assert payload["NEXTCLOUD_USERNAME"] == "alice"
    assert payload["NEXTCLOUD_PASSWORD"] == "secret"


def test_write_persisted_settings_serializes_yandex_client_credentials(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="yandex",
        yandex_token="token",
        yandex_client_id="client-id",
        yandex_client_secret="client-secret",
    )

    config_path = config.write_persisted_settings()
    payload = json.loads(config_path.read_text(encoding="utf-8"))

    assert payload["YANDEX_DISK_TOKEN"] == "token"
    assert payload["YANDEX_CLIENT_ID"] == "client-id"
    assert payload["YANDEX_CLIENT_SECRET"] == "client-secret"
