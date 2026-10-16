import os
import shutil
import subprocess
import tomllib

from . import paths


def settings():
    try:
        return tomllib.loads(paths.SETTINGS.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def hook():
    return os.environ.get("BLACKWALL_NOTIFY") or settings().get("notify")


def quietly(command, **kwargs):
    try:
        subprocess.run(command, capture_output=True, timeout=30, **kwargs)
    except (OSError, subprocess.SubprocessError):
        pass


def send(title, message, **fields):
    """A desktop notification, plus the `notify` command from config.toml or BLACKWALL_NOTIFY (one that pushes to a phone,
    say), which reads the text from BLACKWALL_TITLE and BLACKWALL_MESSAGE. A failing notifier never fails a run."""
    if shutil.which("notify-send"):
        quietly(["notify-send", "-a", "blackwall", title, message])
    command = hook()
    if command:
        environment = {**os.environ, "BLACKWALL_TITLE": title, "BLACKWALL_MESSAGE": message,
                       **{f"BLACKWALL_{key.upper()}": str(value) for key, value in fields.items()}}
        quietly(command, shell=True, env=environment)
