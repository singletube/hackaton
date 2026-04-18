from __future__ import annotations

import shutil
import subprocess


def copy_text_to_clipboard(text: str) -> bool:
    commands = _clipboard_commands()
    for command in commands:
        try:
            subprocess.run(
                command,
                input=text,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except (OSError, subprocess.CalledProcessError):
            continue
    return False


def _clipboard_commands() -> list[list[str]]:
    commands: list[list[str]] = []
    if shutil.which("wl-copy"):
        commands.append(["wl-copy"])
    if shutil.which("xclip"):
        commands.append(["xclip", "-selection", "clipboard"])
    if shutil.which("xsel"):
        commands.append(["xsel", "--clipboard", "--input"])
    if shutil.which("clip.exe"):
        commands.append(["clip.exe"])
    if shutil.which("clip"):
        commands.append(["clip"])
    return commands
