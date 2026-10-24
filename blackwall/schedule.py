import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import gpu, notify, paths, store, swap, units

TIMER = "blackwall-tick"
UNIT_DIR = Path(os.environ.get("XDG_CONFIG_HOME", paths.HOME / ".config")) / "systemd" / "user"
PASSED_ENV = ("XDG_CACHE_HOME", "XDG_CONFIG_HOME")


def parse_clock(text):
    """HH:MM on a 24-hour clock, returned zero-padded; a ValueError names what was wrong."""
    try:
        moment = datetime.strptime(text.strip(), "%H:%M")
    except ValueError:
        raise ValueError(f"'{text}' is not a time like 03:00") from None
    return moment.strftime("%H:%M")


def parse_at(text):
    """A clock time (the next time it comes round) or a full date and time; returns (first start or None, clock)."""
    for layout in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            moment = datetime.strptime(text.strip(), layout)
        except ValueError:
            continue
        return moment, moment.strftime("%H:%M")
    return None, parse_clock(text)


def minute_of(clock):
    hours, minutes = map(int, clock.split(":"))
    return hours * 60 + minutes


def in_window(moment, window):
    """Whether a moment falls in a daily window; a window without an end never closes, and one like 23:00–07:00 spans midnight."""
    if not window or not window.get("end"):
        return True
    start, end, now = minute_of(window["start"]), minute_of(window["end"]), moment.hour * 60 + moment.minute
    return start <= now < end if start < end else now >= start or now < end


def next_start(moment, clock):
    hours, minutes = map(int, clock.split(":"))
    candidate = moment.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    return candidate if candidate >= moment else candidate + timedelta(days=1)


def window_deadline(window, moment):
    """When the window that is open now closes; None for a window without an end, or when it isn't open."""
    if not window or not window.get("end") or not in_window(moment, window):
        return None
    return next_start(moment, window["end"]).timestamp()


def first_start(moment, window, at=None):
    """When a newly scheduled run may begin: the given date, now if already inside its window, else the next window start."""
    if at is not None:
        return max(at, moment)
    if window.get("end") and in_window(moment, window):
        return moment
    return next_start(moment, window["start"])


RECOVERY_BUDGET = 6
RECOVERY_BACKOFF_S = (0, 60, 120, 300)


def arm_wake(seconds, run_id):
    """A tick exactly when a recovering run is due again, so its retry does not sit out the five-minute timer. A
    failure here only costs that wait: the timer still comes."""
    delay = max(0, int(seconds))
    name = "blackwall-wake-" + "".join(character if character.isalnum() or character in "._-" else "_" for character in run_id)
    subprocess.run(["systemd-run", "--user", "--collect", f"--on-active={delay}s", f"--unit={name}",
                    sys.executable, "-m", "blackwall.cli", "tick"], capture_output=True)


def last_progress(run_id):
    """Where a vanished worker had got to, read off the events it wrote before it went."""
    try:
        with (paths.RUNS / run_id / "events.jsonl").open() as handle:
            events = [json.loads(line) for line in handle if line.strip()]
    except (OSError, ValueError):
        return "the start"
    for event in reversed(events):
        if event.get("phase") and event.get("done") is not None:
            total = event.get("total")
            return f"{event['phase']} {event['done']}" + (f"/{total}" if total else "")
    return "the start"


def recover(db, run):
    """Puts a run whose worker vanished back on the schedule instead of burying it: the answers are on disk, so the
    next worker continues from them. Each try waits longer than the last, so a machine that reboots in a loop does not
    spin, and past the budget the run stops being retried with the place it got to written down."""
    flags = run.get("flags") or {}
    tries = int(flags.get("recovered") or 0)
    where = last_progress(run["id"])
    if tries >= RECOVERY_BUDGET:
        store.update_run(db, run["id"], status="failed", finished=time.time(),
                         error=f"the worker stopped {tries} times without finishing, the last at {where}")
        note(run["id"], f"given up after {tries} interruptions, the last at {where}")
        notify.send("Blackwall gave up", f"{run['model']}: stopped {tries} times, the last at {where}",
                    run=run["id"], status="failed")
        return None
    not_before = time.time() + RECOVERY_BACKOFF_S[min(tries, len(RECOVERY_BACKOFF_S) - 1)]
    reason = f"recovering after the worker stopped at {where}"
    store.update_run(db, run["id"], status="scheduled", error=None, finished=None,
                     flags={**flags, "not_before": not_before, "recovered": tries + 1, "recovered_from": where,
                            "parked": reason})
    note(run["id"], f"{reason}; continuing {describe(not_before)}")
    if not_before > time.time():
        arm_wake(not_before - time.time() + 1, run["id"])
    notify.send("Blackwall recovered", f"{run['model']}: the worker stopped at {where}; continuing {describe(not_before)}",
                run=run["id"], status="scheduled")
    return not_before


def describe(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%a %d %b %H:%M")


def tick_command():
    """What the tick unit runs: the installed `blackwall` when there is one, so the unit does not depend on which
    interpreter happened to write it last. A unit pinned to a system Python that cannot import Blackwall fails every
    five minutes and starts nothing."""
    installed = shutil.which("blackwall")
    return f"{installed} tick" if installed else f"{sys.executable} -m blackwall.cli tick"


def unit_files():
    environment = {key: value for key, value in os.environ.items() if key.startswith("BLACKWALL_") or key in PASSED_ENV}
    service = (
        "[Unit]\nDescription=Start due Blackwall runs and pause runs outside their window\n\n[Service]\nType=oneshot\n"
        + "".join(f'Environment="{key}={value}"\n' for key, value in sorted(environment.items()))
        + f"WorkingDirectory={paths.DATA}\nExecStart={tick_command()}\n"
    )
    timer = ("[Unit]\nDescription=Check the Blackwall schedule every five minutes\n\n[Timer]\nOnCalendar=*:0/5\n"
             "OnBootSec=90s\nAccuracySec=1s\n\n[Install]\nWantedBy=timers.target\n")
    return {f"{TIMER}.service": service, f"{TIMER}.timer": timer}


def install_timer():
    """A persistent user timer, so a schedule survives reboots and logouts (with lingering on)."""
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    changed = False
    for name, text in unit_files().items():
        path = UNIT_DIR / name
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
            changed = True
    if changed:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{TIMER}.timer"], check=True, capture_output=True)


def remove_timer():
    subprocess.run(["systemctl", "--user", "disable", "--now", f"{TIMER}.timer"], capture_output=True)


def note(run_id, message):
    log = paths.RUNS / run_id / "worker.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as handle:
        handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def gives_way(flags):
    """Every run steps aside for a game or another GPU job unless it was started with --keep-gpu."""
    return flags.get("yield", True)


def park(db, run_id, not_before, reason, counter):
    """Puts a run back on the schedule to continue from its saved answers; counter is "paused" for a closing window and
    "yielded" for giving the GPU away. Returns how many times that has happened to the run."""
    flags = (store.get_run(db, run_id) or {}).get("flags") or {}
    count = flags.get(counter, 0) + 1
    store.update_run(db, run_id, status="scheduled",
                     flags={**flags, "not_before": not_before, counter: count, "parked": reason})
    note(run_id, f"paused: {reason}; continues {describe(not_before)} at the earliest")
    return count


def pause(db, run, moment):
    """Stops a run whose window closed and frees the GPU; its saved answers carry it on when the window next opens."""
    window = (run.get("flags") or {})["window"]
    units.stop(run["id"])
    swap.unload()
    resumes = next_start(moment, window["start"]).timestamp()
    if park(db, run["id"], resumes, f"the window closed at {window['end']}", "paused") == 1:
        notify.send("Blackwall paused", f"{run['model']}: the window closed at {window['end']}; continues {describe(resumes)}",
                    run=run["id"], status="paused")


def due(run, moment):
    return ((run.get("flags") or {}).get("not_before") or 0) <= moment.timestamp()


def in_flight(run):
    """A run that has started and has not finished: it is on the device, or waiting out the program that took it.
    The queue drains before it fills, so a run three hours into a suite is never left half-measured because a model
    queued behind it happened to be ready while it was giving the card away. A run parked by its own daily window is
    not in flight: it is waiting for tomorrow, and the card should go to something that can use it tonight."""
    flags = run.get("flags") or {}
    if run["status"] in units.ACTIVE:
        return True
    return (run["status"] == "scheduled" and run.get("started") is not None
            and bool(flags.get("yielded") or flags.get("recovered")))


def tick(db, moment=None):
    """Pauses runs whose window has closed, then starts every due scheduled run whose device is free; returns the
    first one it started. A phone and the card are separate machines, so one never waits for the other."""
    moment = moment or datetime.now()
    units.reconcile(db)
    for run in store.list_runs(db):
        if run["status"] in units.ACTIVE and not in_window(moment, (run.get("flags") or {}).get("window")):
            pause(db, run, moment)
    runs = store.list_runs(db)
    started = None
    waiting = sorted((run for run in runs if run["status"] == "scheduled" and due(run, moment)),
                     key=lambda run: ((run.get("flags") or {}).get("not_before") or 0, run.get("created") or 0))
    contended = None
    for run in waiting:
        device = units.device_class(run)
        if units.busy(runs, device, speed=units.measures_speed(run)):
            continue
        if not run.get("started") and any(
                other["id"] != run["id"] and units.device_class(other) == device and in_flight(other) for other in runs):
            continue
        flags = run.get("flags") or {}
        if not in_window(moment, flags.get("window")):
            later = next_start(moment, flags["window"]["start"]).timestamp()
            store.update_run(db, run["id"], flags={**flags, "not_before": later})
            continue
        if gives_way(flags) and units.device_class(run) == units.GPU_CLASS:
            contended = gpu.contention() if contended is None else contended
            if contended:
                continue
        store.update_run(db, run["id"], status="queued", error=None)
        units.spawn(run["id"], False)
        runs = store.list_runs(db)
        started = started or run["id"]
    if not any(run["status"] == "scheduled" for run in store.list_runs(db)):
        remove_timer()
    return started
