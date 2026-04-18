import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

CLOUDBRIDGE_REMOTE_ATTR = "user.cloudbridge.remote"


def set_placeholder_remote_path(local_path: str | os.PathLike, remote_path: str) -> bool:
    path = Path(local_path)
    try:
        os.setxattr(path, CLOUDBRIDGE_REMOTE_ATTR, remote_path.encode("utf-8"))
        return True
    except (AttributeError, OSError) as exc:
        logger.warning("Could not set CloudBridge xattr on %s: %s", path, exc)
        return False


def get_placeholder_remote_path(local_path: str | os.PathLike) -> str | None:
    path = Path(local_path)
    try:
        value = os.getxattr(path, CLOUDBRIDGE_REMOTE_ATTR)
    except (AttributeError, OSError):
        return None
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return None


def remove_placeholder_remote_path(local_path: str | os.PathLike):
    path = Path(local_path)
    try:
        os.removexattr(path, CLOUDBRIDGE_REMOTE_ATTR)
    except (AttributeError, OSError):
        pass
