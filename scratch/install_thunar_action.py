import argparse
import os
import xml.etree.ElementTree as ET
from pathlib import Path


ACTION_NAME = "Open with CloudBridge"


def _indent(element, level=0):
    space = "\n" + level * "  "
    if len(element):
        if not element.text or not element.text.strip():
            element.text = space + "  "
        for child in element:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = space
    if level and (not element.tail or not element.tail.strip()):
        element.tail = space


def _load_or_create(path: Path):
    if path.exists():
        tree = ET.parse(path)
        root = tree.getroot()
        if root.tag != "actions":
            raise RuntimeError(f"Unexpected Thunar action root in {path}: {root.tag}")
        return tree, root

    root = ET.Element("actions")
    return ET.ElementTree(root), root


def _remove_existing(root):
    for action in list(root.findall("action")):
        name = action.findtext("name")
        if name == ACTION_NAME:
            root.remove(action)


def _add_action(root, command: str):
    action = ET.SubElement(root, "action")
    ET.SubElement(action, "icon").text = "folder-cloud"
    ET.SubElement(action, "name").text = ACTION_NAME
    ET.SubElement(action, "submenu").text = ""
    ET.SubElement(action, "unique-id").text = "cloudbridge-open"
    ET.SubElement(action, "command").text = command
    ET.SubElement(action, "description").text = "Download, open, upload changes, then clean up"
    ET.SubElement(action, "range").text = "*"
    ET.SubElement(action, "patterns").text = "*"
    ET.SubElement(action, "directories").text = "FALSE"
    ET.SubElement(action, "audio-files").text = "TRUE"
    ET.SubElement(action, "image-files").text = "TRUE"
    ET.SubElement(action, "other-files").text = "TRUE"
    ET.SubElement(action, "text-files").text = "TRUE"
    ET.SubElement(action, "video-files").text = "TRUE"


def parse_args():
    parser = argparse.ArgumentParser(description="Install Thunar custom action for CloudBridge.")
    parser.add_argument("--project-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--local-path", required=True, help="Folder with visible placeholders, e.g. /home/kali/Videos/copypapka")
    parser.add_argument("--remote-root", default=os.getenv("YANDEX_PATH", "/CloudBridgeTest"))
    parser.add_argument("--token", default=os.getenv("YANDEX_TOKEN"))
    parser.add_argument("--env-file", default="")
    parser.add_argument("--python-bin", default="python3")
    parser.add_argument(
        "--editor",
        default="auto",
        help="Application command. Use auto to open each file with the system default app.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.token and not args.env_file:
        raise RuntimeError("Provide --token or export YANDEX_TOKEN before installing the action")

    config_path = Path.home() / ".config" / "Thunar" / "uca.xml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    project_dir = Path(args.project_dir).expanduser().resolve()
    open_command = "" if args.editor == "auto" else f" --command {args.editor}"
    env_setup = ""
    if args.env_file:
        env_setup = f"source \"{Path(args.env_file).expanduser()}\" && "
    else:
        env_setup = (
            f"export YANDEX_TOKEN=\"{args.token}\" && "
            f"export YANDEX_PATH=\"{args.remote_root}\" && "
            f"export LOCAL_PATH=\"{args.local_path}\" && "
        )
    command = (
        "exo-open --launch TerminalEmulator bash -lc "
        f"'cd {project_dir} && "
        f"{env_setup}"
        f"\"{args.python_bin}\" -m src.cloud_open \"%f\"{open_command}'"
    )

    tree, root = _load_or_create(config_path)
    _remove_existing(root)
    _add_action(root, command)
    _indent(root)
    tree.write(config_path, encoding="UTF-8", xml_declaration=True)

    print(f"Installed Thunar action: {ACTION_NAME}")
    print(f"Config: {config_path}")
    print("Restart Thunar with: thunar -q")


if __name__ == "__main__":
    main()
