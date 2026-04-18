import argparse
import os
import xml.etree.ElementTree as ET
from pathlib import Path


OPEN_ACTION_NAME = "Open with CloudBridge"
STORE_LOCAL_ACTION_NAME = "Store Locally"
RESTORE_CLOUD_ACTION_NAME = "Restore to Cloud"
SHARE_READ_ACTION_NAME = "Create Read-only Link"
LEGACY_SHARE_EDIT_ACTION_NAME = "Create Editable Link"


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
        if name in {
            OPEN_ACTION_NAME,
            STORE_LOCAL_ACTION_NAME,
            RESTORE_CLOUD_ACTION_NAME,
            SHARE_READ_ACTION_NAME,
            LEGACY_SHARE_EDIT_ACTION_NAME,
        }:
            root.remove(action)


def _add_action(root, name: str, command: str, description: str, icon: str):
    action = ET.SubElement(root, "action")
    ET.SubElement(action, "icon").text = icon
    ET.SubElement(action, "name").text = name
    ET.SubElement(action, "submenu").text = "CloudBridge"
    ET.SubElement(action, "unique-id").text = name.lower().replace(" ", "-")
    ET.SubElement(action, "command").text = command
    ET.SubElement(action, "description").text = description
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
        env_path = Path(args.env_file).expanduser()
        env_setup = f"if [ -f \"{env_path}\" ]; then source \"{env_path}\"; fi && "
    else:
        env_setup = (
            f"export YANDEX_TOKEN=\"{args.token}\" && "
            f"export YANDEX_PATH=\"{args.remote_root}\" && "
            f"export LOCAL_PATH=\"{args.local_path}\" && "
        )
    open_action_command = (
        "exo-open --launch TerminalEmulator bash -lc "
        f"'cd {project_dir} && "
        f"{env_setup}"
        f"\"{args.python_bin}\" -m src.cloud_open \"%f\"{open_command}'"
    )
    store_local_command = (
        "exo-open --launch TerminalEmulator bash -lc "
        f"'cd {project_dir} && "
        f"{env_setup}"
        f"\"{args.python_bin}\" -m src.keep_local \"%f\"; "
        "read -r -p \"Press Enter to close...\"'"
    )
    restore_cloud_command = (
        "exo-open --launch TerminalEmulator bash -lc "
        f"'cd {project_dir} && "
        f"{env_setup}"
        f"\"{args.python_bin}\" -m src.restore_cloud \"%f\"; "
        "read -r -p \"Press Enter to close...\"'"
    )
    share_read_command = (
        "bash -lc "
        f"'mkdir -p \"$HOME/.cache/cloudbridge\" && "
        f"cd {project_dir} && "
        f"{env_setup}"
        f"\"{args.python_bin}\" -m src.share_link \"%f\" "
        ">> \"$HOME/.cache/cloudbridge/actions.log\" 2>&1 &'"
    )

    tree, root = _load_or_create(config_path)
    _remove_existing(root)
    _add_action(
        root,
        OPEN_ACTION_NAME,
        open_action_command,
        "Download, open, upload changes, then clean up",
        "folder-cloud",
    )
    _add_action(
        root,
        STORE_LOCAL_ACTION_NAME,
        store_local_command,
        "Download this file over the placeholder and ignore future uploads",
        "document-save",
    )
    _add_action(
        root,
        RESTORE_CLOUD_ACTION_NAME,
        restore_cloud_command,
        "Upload this local file back to Yandex.Disk and replace it with a placeholder",
        "folder-cloud",
    )
    _add_action(
        root,
        SHARE_READ_ACTION_NAME,
        share_read_command,
        "Create a read-only Yandex.Disk public link and copy it to clipboard",
        "emblem-shared",
    )
    _indent(root)
    tree.write(config_path, encoding="UTF-8", xml_declaration=True)

    print(f"Installed Thunar action: {OPEN_ACTION_NAME}")
    print(f"Installed Thunar action: {STORE_LOCAL_ACTION_NAME}")
    print(f"Installed Thunar action: {RESTORE_CLOUD_ACTION_NAME}")
    print(f"Installed Thunar action: {SHARE_READ_ACTION_NAME}")
    print(f"Config: {config_path}")
    print("Restart Thunar with: thunar -q")


if __name__ == "__main__":
    main()
