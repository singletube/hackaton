import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = "/tmp/state.db"
DEFAULT_CACHE_DIR = "/tmp/cache"
DEFAULT_MOUNT_POINT = "/tmp/yandex_mount"
DEFAULT_MIRROR_DIR = "/tmp/yandex_mirror"
DEFAULT_DAEMON_LOG_PATH = "/tmp/cloudbridge-daemon.log"
DEFAULT_STATUS_PATH = "/tmp/cloudbridge-status.json"
DEFAULT_PID_PATH = "/tmp/cloudbridge-daemon.pid"


@dataclass
class CloudBridgeConfig:
    token: str
    remote_root: str
    db_path: str
    cache_dir: str
    mount_point: str
    mirror_dir: str
    daemon_log_path: str
    status_path: str
    pid_path: str


def load_runtime_config() -> CloudBridgeConfig:
    return CloudBridgeConfig(
        token=os.getenv("YANDEX_TOKEN", ""),
        remote_root=os.getenv("YANDEX_PATH", "/"),
        db_path=os.getenv("CLOUDBRIDGE_DB_PATH", DEFAULT_DB_PATH),
        cache_dir=os.getenv("CLOUDBRIDGE_CACHE_DIR", DEFAULT_CACHE_DIR),
        mount_point=os.getenv("MOUNT_POINT", DEFAULT_MOUNT_POINT),
        mirror_dir=os.getenv("LOCAL_PATH", DEFAULT_MIRROR_DIR),
        daemon_log_path=os.getenv("CLOUDBRIDGE_DAEMON_LOG", DEFAULT_DAEMON_LOG_PATH),
        status_path=os.getenv("CLOUDBRIDGE_STATUS_PATH", DEFAULT_STATUS_PATH),
        pid_path=os.getenv("CLOUDBRIDGE_PID_PATH", DEFAULT_PID_PATH),
    )


def ensure_runtime_directories(config: CloudBridgeConfig):
    for path in (config.cache_dir, config.mount_point, config.mirror_dir):
        try:
            os.makedirs(path, exist_ok=True)
        except FileExistsError:
            # Mount point can temporarily exist as a non-directory artifact.
            if path == config.mount_point:
                continue
            raise


def _atomic_json_write(path: str, payload: dict[str, Any]):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(target.parent), encoding="utf-8") as tmp_file:
        json.dump(payload, tmp_file, ensure_ascii=True, indent=2)
        tmp_file.write("\n")
        temp_name = tmp_file.name
    os.replace(temp_name, target)


def write_status(path: str, state: str, message: str = "", **extra: Any):
    payload: dict[str, Any] = {"state": state, "message": message}
    payload.update(extra)
    _atomic_json_write(path, payload)


def write_pid(path: str, pid: int):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(pid), encoding="utf-8")


def remove_pid(path: str):
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass

