from __future__ import annotations

from pathlib import Path

import pytest

from cloudbridge.config import AppConfig
from cloudbridge.integration import (
    detect_file_manager,
    install_caja_integration,
    install_nautilus_integration,
    install_nemo_integration,
    install_thunar_integration,
    render_caja_action_desktop,
    render_launcher_script,
    render_nautilus_extension,
    render_nemo_action,
    render_thunar_uca_xml,
)


def test_render_launcher_script_exports_runtime_environment(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="yandex",
        yandex_token="test-token",
        watcher_backend="watchdog",
        scan_concurrency=3,
        sync_concurrency=5,
    )

    script = render_launcher_script(config, tmp_path / "repo", Path("/snap/bin/uv"))

    assert "export YANDEX_DISK_TOKEN=test-token" in script
    assert "export CLOUDBRIDGE_IMPORT_ROOT=/" in script
    assert "export CLOUDBRIDGE_IMPORT_LAYOUT=flat" in script
    assert "export CLOUDBRIDGE_SYNC_ROOT=" in script
    assert 'exec /snap/bin/uv run --project' in script
    assert 'cloudbridge "$@"' in script


def test_render_nautilus_extension_binds_launcher_and_actions(tmp_path: Path) -> None:
    content = render_nautilus_extension(tmp_path / "cloudbridge-nautilus", tmp_path / "mirror")

    assert "\"upload-selected\"" in content
    assert "label=\"Upload to Cloud\"" in content
    assert "label=\"Download from Cloud\"" in content
    assert "label=\"Free Local Space\"" in content


def test_render_thunar_uca_xml_binds_upload_action(tmp_path: Path) -> None:
    content = render_thunar_uca_xml(tmp_path / "cloudbridge-thunar")

    assert "<name>CloudBridge Upload to Cloud</name>" in content
    assert "upload-selected %F" in content
    assert "cloudbridge-managed" in content


def test_render_nemo_action_binds_upload_action(tmp_path: Path) -> None:
    content = render_nemo_action(tmp_path / "cloudbridge-nemo")

    assert "[Nemo Action]" in content
    assert "upload-selected %F" in content
    assert "Selection=notnone" in content


def test_render_caja_action_desktop_binds_upload_action(tmp_path: Path) -> None:
    content = render_caja_action_desktop(tmp_path / "cloudbridge-caja")

    assert "[Desktop Entry]" in content
    assert "Type=Action" in content
    assert "upload-selected %F" in content


def test_install_nautilus_integration_writes_files(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="yandex",
        yandex_token="test-token",
        watcher_backend="watchdog",
    )
    uv_path = tmp_path / "uv"
    uv_path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    result = install_nautilus_integration(
        config,
        repo_root=tmp_path / "repo",
        uv_path=str(uv_path),
        extension_dir=tmp_path / "extensions",
        launcher_path=tmp_path / "bin" / "cloudbridge-nautilus",
    )

    assert result.launcher_path.exists()
    assert result.extension_path.exists()
    launcher_content = result.launcher_path.read_text(encoding="utf-8")
    extension_content = result.extension_path.read_text(encoding="utf-8")
    assert "YANDEX_DISK_TOKEN" in launcher_content
    assert repr(str(result.launcher_path)) in extension_content


def test_install_thunar_integration_writes_files(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="yandex",
        yandex_token="test-token",
        watcher_backend="watchdog",
    )
    uv_path = tmp_path / "uv"
    uv_path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    result = install_thunar_integration(
        config,
        repo_root=tmp_path / "repo",
        uv_path=str(uv_path),
        config_path=tmp_path / "uca.xml",
        launcher_path=tmp_path / "bin" / "cloudbridge-thunar",
    )

    assert result.launcher_path.exists()
    assert result.config_path.exists()
    launcher_content = result.launcher_path.read_text(encoding="utf-8")
    config_content = result.config_path.read_text(encoding="utf-8")
    assert "CLOUDBRIDGE_IMPORT_ROOT" in launcher_content
    assert "upload-selected %F" in config_content


def test_install_nemo_integration_writes_files(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="yandex",
        yandex_token="test-token",
        watcher_backend="watchdog",
    )
    uv_path = tmp_path / "uv"
    uv_path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    result = install_nemo_integration(
        config,
        repo_root=tmp_path / "repo",
        uv_path=str(uv_path),
        actions_dir=tmp_path / "actions",
        launcher_path=tmp_path / "bin" / "cloudbridge-nemo",
    )

    assert result.launcher_path.exists()
    assert result.action_path.exists()
    assert "CLOUDBRIDGE_IMPORT_ROOT" in result.launcher_path.read_text(encoding="utf-8")
    assert "upload-selected %F" in result.action_path.read_text(encoding="utf-8")


def test_install_caja_integration_writes_files(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="yandex",
        yandex_token="test-token",
        watcher_backend="watchdog",
    )
    uv_path = tmp_path / "uv"
    uv_path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    result = install_caja_integration(
        config,
        repo_root=tmp_path / "repo",
        uv_path=str(uv_path),
        actions_dir=tmp_path / "actions",
        launcher_path=tmp_path / "bin" / "cloudbridge-caja",
    )

    assert result.launcher_path.exists()
    assert result.action_path.exists()
    assert "CLOUDBRIDGE_IMPORT_ROOT" in result.launcher_path.read_text(encoding="utf-8")
    assert "upload-selected %F" in result.action_path.read_text(encoding="utf-8")


def test_install_nautilus_integration_requires_token_for_yandex(tmp_path: Path) -> None:
    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="yandex",
        yandex_token=None,
        watcher_backend="watchdog",
    )

    with pytest.raises(ValueError):
        install_nautilus_integration(config, repo_root=tmp_path / "repo", uv_path="/snap/bin/uv")


def test_detect_file_manager_prefers_desktop_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "XFCE")
    monkeypatch.setenv("DESKTOP_SESSION", "xfce")

    assert detect_file_manager() == "thunar"


def test_detect_file_manager_recognizes_mate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "MATE")
    monkeypatch.setenv("DESKTOP_SESSION", "mate")

    assert detect_file_manager() == "caja"
