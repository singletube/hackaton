import argparse
import os
import shlex
from pathlib import Path


def quote(value: str) -> str:
    return shlex.quote(value)


def parse_args():
    parser = argparse.ArgumentParser(description="Write CloudBridge environment config.")
    parser.add_argument("--token", default=os.getenv("YANDEX_TOKEN"))
    parser.add_argument("--remote-root", default=os.getenv("YANDEX_PATH", "/CloudBridgeTest"))
    parser.add_argument("--local-path", default=os.getenv("LOCAL_PATH", "/home/kali/Videos/copypapka"))
    parser.add_argument("--project-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--python-bin", default=os.getenv("CLOUDBRIDGE_PYTHON", "python3"))
    parser.add_argument("--env-file", default="~/.config/cloudbridge/env")
    parser.add_argument("--remote-poll-interval", default=os.getenv("CLOUDBRIDGE_REMOTE_POLL_INTERVAL", "60"))
    return parser.parse_args()


def main():
    args = parse_args()
    token = args.token or input("Yandex OAuth token: ").strip()
    if not token:
        raise RuntimeError("Yandex OAuth token is required")

    env_file = Path(args.env_file).expanduser()
    config_dir = env_file.parent
    cache_dir = Path("~/.cache/cloudbridge").expanduser()
    db_path = cache_dir / "state.db"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    content = "\n".join([
        f"export YANDEX_TOKEN={quote(token)}",
        f"export YANDEX_PATH={quote(args.remote_root)}",
        f"export LOCAL_PATH={quote(args.local_path)}",
        f"export CLOUDBRIDGE_IGNORE_FILE={quote(str(config_dir / 'ignored.json'))}",
        f"export CLOUDBRIDGE_PROJECT_DIR={quote(str(Path(args.project_dir).expanduser().resolve()))}",
        f"export CLOUDBRIDGE_PYTHON={quote(args.python_bin)}",
        f"export CLOUDBRIDGE_DB_PATH={quote(str(db_path))}",
        f"export CLOUDBRIDGE_REMOTE_POLL_INTERVAL={quote(str(args.remote_poll_interval))}",
        "export CLOUDBRIDGE_TEXT_EDITOR=mousepad",
        "export CLOUDBRIDGE_UNKNOWN_EDITOR=mousepad",
        "export CLOUDBRIDGE_IMAGE_VIEWER=ristretto",
        "export PYTHONUNBUFFERED=1",
        "",
    ])
    env_file.write_text(content, encoding="utf-8")
    env_file.chmod(0o600)
    db_path.touch(exist_ok=True)
    db_path.chmod(0o600)
    Path(args.local_path).expanduser().mkdir(parents=True, exist_ok=True)
    print(f"Wrote CloudBridge env config: {env_file}")
    print("Token saved locally and was not printed.")


if __name__ == "__main__":
    main()
