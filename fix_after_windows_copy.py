from pathlib import Path
import os
import stat


ROOT = Path(__file__).resolve().parent
TEXT_EXTENSIONS = {".sh", ".py"}


def normalize_line_endings(path: Path) -> bool:
    data = path.read_bytes()
    normalized = data.replace(b"\r\n", b"\n")
    if normalized == data:
        return False
    path.write_bytes(normalized)
    return True


def ensure_shell_executable(path: Path) -> bool:
    if path.suffix != ".sh":
        return False
    current_mode = path.stat().st_mode
    desired_mode = current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    if desired_mode == current_mode:
        return False
    os.chmod(path, desired_mode)
    return True


def main() -> None:
    fixed_line_endings = 0
    fixed_permissions = 0

    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_EXTENSIONS:
            continue
        if normalize_line_endings(path):
            fixed_line_endings += 1
        if ensure_shell_executable(path):
            fixed_permissions += 1

    print(f"[CloudBridge fix] normalized line endings: {fixed_line_endings}")
    print(f"[CloudBridge fix] updated shell permissions: {fixed_permissions}")
    print("[CloudBridge fix] next step: ./setup_kali.sh")


if __name__ == "__main__":
    main()
