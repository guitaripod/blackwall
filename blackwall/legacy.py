import os
from pathlib import Path

from . import paths

SILENT = ("worker", "tick")


def pairs():
    """Where mbench, the name this project had before 2.0, kept its files, beside where Blackwall keeps them now. Someone
    who points BLACKWALL_HOME somewhere has chosen where their data lives and is not asked to move it."""
    config = Path(os.environ.get("XDG_CONFIG_HOME", paths.HOME / ".config"))
    cache = Path(os.environ.get("XDG_CACHE_HOME", paths.HOME / ".cache"))
    found = [(config / "mbench", paths.CONFIG), (cache / "mbench", paths.CACHE)]
    if "BLACKWALL_HOME" not in os.environ:
        found.insert(0, (paths.HOME / ".local/share/mbench", paths.DATA))
    return tuple(found)


def hint(found=None):
    """Old mbench directories that nothing has replaced yet, with the command that moves each one. Blackwall never moves
    them itself: they hold every answer a night of benchmarking produced, and that is the user's to move."""
    waiting = [(old, new) for old, new in (found or pairs()) if old.exists() and not new.exists()]
    if not waiting:
        return None

    def shown(path):
        return str(path).replace(str(paths.HOME), "~")

    lines = ["blackwall: mbench files found. Blackwall was called mbench before 2.0 and keeps its files under the new name:"]
    lines += [f"  mv {shown(old)} {shown(new)}" for old, new in waiting]
    return "\n".join(lines)
