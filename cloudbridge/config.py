from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    provider_type: str
    token: Optional[str]
    nextcloud_url: Optional[str]
    nextcloud_user: Optional[str]
    nextcloud_pass: Optional[str]
    db_path: Path
    local_root: Path
    cloud_root: str
    max_depth: int


def load_settings() -> Settings:
    load_dotenv()
    provider_type = os.getenv("CLOUDBRIDGE_PROVIDER", "yandex")
    token = os.getenv("YA_DISK_TOKEN")
    nextcloud_url = os.getenv("NEXTCLOUD_URL")
    nextcloud_user = os.getenv("NEXTCLOUD_USER")
    nextcloud_pass = os.getenv("NEXTCLOUD_PASS")
    db_path = Path(os.getenv("CLOUDBRIDGE_DB_PATH", ".cloudbridge/state.db"))
    local_root = Path(os.getenv("CLOUDBRIDGE_LOCAL_ROOT", ".")).resolve()
    cloud_root = os.getenv("CLOUDBRIDGE_CLOUD_ROOT", "disk:/")
    max_depth = int(os.getenv("CLOUDBRIDGE_DISCOVERY_DEPTH", "-1"))
    return Settings(
        provider_type=provider_type,
        token=token,
        nextcloud_url=nextcloud_url,
        nextcloud_user=nextcloud_user,
        nextcloud_pass=nextcloud_pass,
        db_path=db_path,
        local_root=local_root,
        cloud_root=cloud_root,
        max_depth=max_depth,
    )
