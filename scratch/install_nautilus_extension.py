import argparse
import shutil
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Install Nautilus extension for CloudBridge.")
    parser.add_argument("--project-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--python-bin", default="python3")
    return parser.parse_args()


def main():
    args = parse_args()
    project_dir = Path(args.project_dir).expanduser().resolve()
    source_path = project_dir / "scratch" / "cloudbridge_nautilus_extension.py"
    if not source_path.exists():
        raise RuntimeError(f"Extension source not found: {source_path}")

    target_dir = Path.home() / ".local" / "share" / "nautilus-python" / "extensions"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "cloudbridge_extension.py"
    shutil.copy2(source_path, target_path)

    print("Installed Nautilus extension: CloudBridge")
    print(f"Source: {source_path}")
    print(f"Target: {target_path}")
    print("Restart Nautilus with: nautilus -q")


if __name__ == "__main__":
    main()
