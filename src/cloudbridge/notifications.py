from __future__ import annotations

import shutil
import subprocess


def send_desktop_notification(summary: str, body: str = "") -> bool:
    if not shutil.which("notify-send"):
        return False
    command = ["notify-send", summary]
    if body:
        command.append(body)
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False
