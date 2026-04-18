from __future__ import annotations

from pathlib import Path

from cloudbridge.config import AppConfig
from cloudbridge.gui import build_gui_config, default_gui_launcher_command


def test_default_gui_launcher_command_prefers_current_argv0(tmp_path: Path) -> None:
    launcher = tmp_path / "cloudbridge-local"
    launcher.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    result = default_gui_launcher_command(str(launcher))

    assert result == str(launcher)


def test_build_gui_config_updates_runtime_values(tmp_path: Path) -> None:
    base = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="yandex",
        yandex_token="token",
    )

    updated = build_gui_config(
        base,
        provider_name="nextcloud",
        sync_root=str(tmp_path / "sync"),
        import_root="/incoming",
        import_layout="by-date",
        watcher_backend="watchdog",
        scan_concurrency=12,
        sync_concurrency=6,
        yandex_token="",
        yandex_client_id="client-id",
        yandex_client_secret="client-secret",
        nextcloud_url="https://cloud.example.test/",
        nextcloud_username="alice",
        nextcloud_password="secret",
    )

    assert updated.provider_name == "nextcloud"
    assert updated.sync_root == tmp_path / "sync"
    assert updated.import_layout == "by-date"
    assert updated.watcher_backend == "watchdog"
    assert updated.scan_concurrency == 12
    assert updated.sync_concurrency == 6
    assert updated.yandex_token is None
    assert updated.yandex_client_id == "client-id"
    assert updated.nextcloud_url == "https://cloud.example.test"
