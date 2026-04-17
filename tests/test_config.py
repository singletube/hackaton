import os
from pathlib import Path
from unittest.mock import patch

from cloudbridge.config import load_settings, Settings

def test_load_settings_defaults(monkeypatch):
    # Clear env vars that might affect the test
    for key in ["CLOUDBRIDGE_PROVIDER", "YA_DISK_TOKEN", "NEXTCLOUD_URL", 
                "NEXTCLOUD_USER", "NEXTCLOUD_PASS", "CLOUDBRIDGE_DB_PATH", 
                "CLOUDBRIDGE_LOCAL_ROOT", "CLOUDBRIDGE_CLOUD_ROOT", 
                "CLOUDBRIDGE_DISCOVERY_DEPTH"]:
        monkeypatch.delenv(key, raising=False)

    settings = load_settings()
    
    assert settings.provider_type == "yandex"
    assert settings.token is None
    assert settings.nextcloud_url is None
    assert settings.nextcloud_user is None
    assert settings.nextcloud_pass is None
    assert settings.db_path == Path(".cloudbridge/state.db")
    assert settings.local_root == Path(".").resolve()
    assert settings.cloud_root == "disk:/"
    assert settings.max_depth == -1

def test_load_settings_with_env_vars(monkeypatch):
    monkeypatch.setenv("CLOUDBRIDGE_PROVIDER", "nextcloud")
    monkeypatch.setenv("YA_DISK_TOKEN", "fake_ya_token")
    monkeypatch.setenv("NEXTCLOUD_URL", "https://nc.example.com")
    monkeypatch.setenv("NEXTCLOUD_USER", "admin")
    monkeypatch.setenv("NEXTCLOUD_PASS", "secret")
    monkeypatch.setenv("CLOUDBRIDGE_DB_PATH", "/tmp/custom.db")
    monkeypatch.setenv("CLOUDBRIDGE_LOCAL_ROOT", "/tmp/local")
    monkeypatch.setenv("CLOUDBRIDGE_CLOUD_ROOT", "/remote")
    monkeypatch.setenv("CLOUDBRIDGE_DISCOVERY_DEPTH", "5")

    settings = load_settings()

    assert settings.provider_type == "nextcloud"
    assert settings.token == "fake_ya_token"
    assert settings.nextcloud_url == "https://nc.example.com"
    assert settings.nextcloud_user == "admin"
    assert settings.nextcloud_pass == "secret"
    assert settings.db_path == Path("/tmp/custom.db")
    assert settings.local_root == Path("/tmp/local").resolve()
    assert settings.cloud_root == "/remote"
    assert settings.max_depth == 5
