import subprocess
from pathlib import Path

import pytest

from blackwall import schedule

REAL_RUN = subprocess.run
CHANGES_SYSTEMD = ("systemd-run", "systemctl")
READS_SYSTEMD = ("is-active", "show", "status", "cat")


def changes_systemd(command):
    if not isinstance(command, (list, tuple)) or not command or Path(str(command[0])).name not in CHANGES_SYSTEMD:
        return False
    return not any(word in command for word in READS_SYSTEMD)


@pytest.fixture(autouse=True)
def systemd(monkeypatch, tmp_path_factory):
    """Stands in for the user's systemd. A test that forgets to stub the scheduler would otherwise start timers, units
    and workers in the real session, or rewrite the unit files the real schedule runs from; instead every command that
    changes systemd is recorded here and answered with success, and the unit files go to a temporary folder."""
    monkeypatch.setattr(schedule, "UNIT_DIR", tmp_path_factory.mktemp("units"))
    commands = []

    def run(command, *args, **kwargs):
        if changes_systemd(command):
            commands.append(list(command))
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return REAL_RUN(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    return commands
