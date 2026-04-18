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
    return parser.parse_args()


def main():
    args = parse_args()
    token = args.token or input("Yandex OAuth token: ").strip()
    if not token:
        raise RuntimeError("Yandex OAuth token is required")

    env_file = Path(args.env_file).expanduser()
    env_file.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join([
        f"export YANDEX_TOKEN={quote(token)}",
        f"export YANDEX_PATH={quote(args.remote_root)}",
        f"export LOCAL_PATH={quote(args.local_path)}",
        f"export CLOUDBRIDGE_PROJECT_DIR={quote(str(Path(args.project_dir).expanduser().resolve()))}",
        f"export CLOUDBRIDGE_PYTHON={quote(args.python_bin)}",
        "export PYTHONUNBUFFERED=1",
        "",
    ])
    env_file.write_text(content, encoding="utf-8")
    env_file.chmod(0o600)
    Path(args.local_path).expanduser().mkdir(parents=True, exist_ok=True)
    print(f"Wrote CloudBridge env config: {env_file}")
    print("Token saved locally and was not printed.")


if __name__ == "__main__":
    main()
