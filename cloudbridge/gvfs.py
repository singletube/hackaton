import os
from pathlib import Path

def get_bookmarks_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return Path(config_home) / "gtk-3.0" / "bookmarks"

def add_bookmark(mountpoint: Path, name: str = "CloudBridge") -> None:
    bm_path = get_bookmarks_path()
    if not bm_path.parent.exists():
        return
    
    uri = f"file://{mountpoint.resolve().as_posix()}"
    line = f"{uri} {name}\n"
    
    if bm_path.exists():
        with bm_path.open("r") as f:
            lines = f.readlines()
        if any(l.startswith(uri) for l in lines):
            return
    else:
        lines = []

    lines.append(line)
    with bm_path.open("w") as f:
        f.writelines(lines)

def remove_bookmark(mountpoint: Path) -> None:
    bm_path = get_bookmarks_path()
    if not bm_path.exists():
        return
    
    uri = f"file://{mountpoint.resolve().as_posix()}"
    
    with bm_path.open("r") as f:
        lines = f.readlines()
    
    new_lines = [l for l in lines if not l.startswith(uri)]
    
    if len(new_lines) != len(lines):
        with bm_path.open("w") as f:
            f.writelines(new_lines)
