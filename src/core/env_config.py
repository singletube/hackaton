import os
import shlex
from pathlib import Path


def default_env_file() -> Path:
    return Path(os.getenv("CLOUDBRIDGE_ENV_FILE", "~/.config/cloudbridge/env")).expanduser()


def load_env_file(path: str | os.PathLike | None = None):
    env_path = Path(path).expanduser() if path else default_env_file()
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        try:
            parsed = shlex.split(value, posix=True)
            value = parsed[0] if parsed else ""
        except ValueError:
            value = value.strip("'\"")
        os.environ.setdefault(key, value)
