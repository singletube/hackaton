import argparse
import configparser
import json
import os
import shutil
import subprocess
from pathlib import Path


DESKTOP_ID = "cloudbridge-open-placeholder.desktop"
MIME_TYPES = [
    "inode/x-empty",
    "application/x-zerosize",
    "application/octet-stream",
    "text/plain",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
]


def _query_default(mime_type: str) -> str:
    process = subprocess.run(["xdg-mime", "query", "default", mime_type], text=True, capture_output=True, check=False)
    return process.stdout.strip()


def _write_desktop_file(launcher: Path):
    app_dir = Path("~/.local/share/applications").expanduser()
    app_dir.mkdir(parents=True, exist_ok=True)
    desktop_path = app_dir / DESKTOP_ID
    mime_list = ";".join(MIME_TYPES) + ";"
    desktop_path.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=CloudBridge Open",
                "Comment=Open CloudBridge placeholders from Yandex.Disk",
                f"Exec={launcher} %f",
                "Terminal=false",
                "NoDisplay=true",
                "Icon=folder-cloud",
                f"MimeType={mime_list}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return desktop_path


def _save_previous_defaults(mime_types: list[str]):
    config_dir = Path("~/.config/cloudbridge").expanduser()
    config_dir.mkdir(parents=True, exist_ok=True)
    defaults_file = config_dir / "mime-defaults.json"
    previous = {}
    if defaults_file.exists():
        try:
            previous = json.loads(defaults_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}

    for mime_type in mime_types:
        previous.setdefault(mime_type, _query_default(mime_type))
    defaults_file.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")


def _force_mimeapps_defaults(mime_types: list[str]):
    mimeapps_path = Path("~/.config/mimeapps.list").expanduser()
    mimeapps_path.parent.mkdir(parents=True, exist_ok=True)

    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    if mimeapps_path.exists():
        parser.read(mimeapps_path, encoding="utf-8")

    if not parser.has_section("Default Applications"):
        parser.add_section("Default Applications")
    if not parser.has_section("Added Associations"):
        parser.add_section("Added Associations")

    for mime_type in mime_types:
        parser["Default Applications"][mime_type] = DESKTOP_ID
        associations = [
            item
            for item in parser["Added Associations"].get(mime_type, "").split(";")
            if item and item != DESKTOP_ID
        ]
        parser["Added Associations"][mime_type] = ";".join([DESKTOP_ID, *associations]) + ";"

    with mimeapps_path.open("w", encoding="utf-8") as f:
        parser.write(f, space_around_delimiters=False)


def install(launcher: Path):
    desktop_path = _write_desktop_file(launcher)
    _save_previous_defaults(MIME_TYPES)
    subprocess.run(["update-desktop-database", str(desktop_path.parent)], check=False)
    for mime_type in MIME_TYPES:
        subprocess.run(["xdg-mime", "default", DESKTOP_ID, mime_type], check=False)
        if shutil.which("gio"):
            subprocess.run(["gio", "mime", mime_type, DESKTOP_ID], check=False)
    _force_mimeapps_defaults(MIME_TYPES)
    print(f"Installed CloudBridge MIME opener: {desktop_path}")
    print("Forced MIME defaults in ~/.config/mimeapps.list")
    print("Previous defaults saved to ~/.config/cloudbridge/mime-defaults.json")


def parse_args():
    parser = argparse.ArgumentParser(description="Install CloudBridge as opener for placeholder files.")
    parser.add_argument("--project-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--env-file", default="~/.config/cloudbridge/env")
    parser.add_argument("--python-bin", default=os.getenv("CLOUDBRIDGE_PYTHON", "python3"))
    parser.add_argument("--launcher", default="~/.local/bin/cloudbridge-open-or-default")
    return parser.parse_args()


def main():
    args = parse_args()
    install(launcher=Path(args.launcher).expanduser())


if __name__ == "__main__":
    main()
