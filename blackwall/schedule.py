import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from . import gpu, notify, paths, store, suite, swap, units

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
WAKE = "blackwall-wake"
WAKE_HORIZON_S = 3600
CAUSES = {"oom-kill": "ran out of memory", "signal": "was killed", "exit-code": "crashed", "core-dump": "crashed",
          "timeout": "stopped answering systemd", "watchdog": "stopped answering systemd"}
TRANSIENT_FLAGS = ("parked", "stall", "holds_card", "recovered", "recovered_from", "recovered_cause", "recovery_streak",
                   "recovery_saved")


def arm(db):
    """A tick at the moment the earliest waiting run is due, so a retry does not sit out the rest of the five-minute
    poll. The unit is named for the second it fires: arming the same moment twice is a no-op, and a tick that arms from
    inside the unit that woke it cannot collide with itself. It starts the tick unit rather than running Blackwall
    itself, so there is one definition of how a tick runs. A failure here only costs the wait: the timer still comes."""
    now = time.time()
    due = [(run.get("flags") or {}).get("not_before") or 0 for run in store.list_runs(db) if run["status"] == "scheduled"]
    upcoming = [each for each in due if now < each < now + WAKE_HORIZON_S]
    if not upcoming:
        return
    moment = int(min(upcoming)) + 1
    subprocess.run(["systemd-run", "--user", "--collect", f"--unit={WAKE}-{moment}",
                    "--on-calendar=" + datetime.fromtimestamp(moment).strftime("%Y-%m-%d %H:%M:%S"),
                    shutil.which("systemctl") or "systemctl", "--user", "start", "--no-block", f"{TIMER}.service"],
                   capture_output=True)


def answers_saved(run_id):
    """How many answers a run has on disk. It only ever grows, so it tells whether a worker that stopped got anywhere."""
    total = 1 if (paths.RUNS / run_id / "speed.json").exists() else 0
    for task in suite.QUALITY_TASKS:
        try:
            with (paths.RUNS / run_id / f"{task}.jsonl").open("rb") as handle:
                total += sum(1 for line in handle if line.strip())
        except OSError:
            continue
    return total


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


def stalled_streak(flags, saved):
    """How many times in a row the worker has stopped without a new answer on disk, counting this one. Interruptions
    that each got somewhere are not a failing run, they are a machine that keeps rebooting: only the ones that got
    nowhere spend the budget."""
    if saved > int(flags.get("recovery_saved", -1)):
        return 1
    return int(flags.get("recovery_streak") or 0) + 1


def recover(db, run, cause=None):
    """Puts a run whose worker vanished back on the schedule instead of burying it: the answers are on disk, so the
    next worker continues from them. cause is the result systemd recorded when it knows one (oom-kill, signal,
    exit-code). Each try without progress waits longer than the last, so a machine that reboots in a loop does not
    spin, and past the budget the run stops being retried with the place it got to written down."""
    run = store.get_run(db, run["id"])
    if not run or run["status"] not in units.ACTIVE:
        return None
    flags = run.get("flags") or {}
    saved = answers_saved(run["id"])
    streak = stalled_streak(flags, saved)
    where = last_progress(run["id"])
    if streak > RECOVERY_BUDGET:
        store.update_run(db, run["id"], status="failed", finished=time.time(),
                         error=f"the worker stopped {streak - 1} times in a row without a new answer, the last at {where}")
        note(run["id"], f"given up after {streak - 1} interruptions without progress, the last at {where}")
        notify.send("Blackwall gave up", f"{run['model']}: stopped {streak - 1} times in a row, the last at {where}",
                    run=run["id"], status="failed")
        return None
    not_before = time.time() + RECOVERY_BACKOFF_S[min(streak - 1, len(RECOVERY_BACKOFF_S) - 1)]
    reason = f"recovering after the worker {CAUSES.get(cause, 'stopped')} at {where}"
    ensure_timer(run["id"])
    store.update_run(db, run["id"], status="scheduled", error=None, finished=None,
                     flags={**flags, "not_before": not_before, "holds_card": True, "parked": reason,
                            "recovered": int(flags.get("recovered") or 0) + 1, "recovered_from": where,
                            "recovered_cause": cause, "recovery_streak": streak, "recovery_saved": saved})
    note(run["id"], f"{reason}; continuing {describe(not_before)}")
    notify.send("Blackwall recovered", f"{run['model']}: the worker {CAUSES.get(cause, 'stopped')} at {where}; "
                f"continuing {describe(not_before)}", run=run["id"], status="scheduled")
    return not_before


def describe(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%a %d %b %H:%M")


def tick_command():
    """What the tick unit runs: the installed `blackwall` when there is one, so the unit does not depend on which
    interpreter happened to write it last. A unit pinned to a system Python that cannot import Blackwall fails every
    five minutes and starts nothing."""
    installed = shutil.which("blackwall")
    return shlex.join([installed, "tick"] if installed else [sys.executable, "-m", "blackwall.cli", "tick"])


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


def ensure_timer(run_id):
    """The unit that brings a recovered run back. Not being able to install it must not leave the run marked running."""
    try:
        install_timer()
    except (subprocess.CalledProcessError, OSError) as error:
        note(run_id, f"could not install the schedule timer: {error!r}")


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


def park(db, run_id, not_before, reason, counter, holds_card):
    """Puts a run back on the schedule to continue from its saved answers; counter is "paused" for a closing window and
    "yielded" for giving the GPU away. holds_card says whether it keeps its place on the device while it waits: a run
    that gave way to a game does, a run waiting for tomorrow's window does not, and each park decides it afresh.
    Returns how many times that has happened to the run."""
    flags = (store.get_run(db, run_id) or {}).get("flags") or {}
    count = flags.get(counter, 0) + 1
    store.update_run(db, run_id, status="scheduled",
                     flags={**flags, "not_before": not_before, counter: count, "parked": reason,
                            "holds_card": holds_card})
    note(run_id, f"paused: {reason}; continues {describe(not_before)} at the earliest")
    return count


def pause(db, run, moment):
    """Stops a run whose window closed and frees the GPU; its saved answers carry it on when the window next opens."""
    window = (run.get("flags") or {})["window"]
    units.stop(run["id"])
    swap.unload()
    resumes = next_start(moment, window["start"]).timestamp()
    if park(db, run["id"], resumes, f"the window closed at {window['end']}", "paused", False) == 1:
        notify.send("Blackwall paused", f"{run['model']}: the window closed at {window['end']}; continues {describe(resumes)}",
                    run=run["id"], status="paused")


def due(run, moment):
    return ((run.get("flags") or {}).get("not_before") or 0) <= moment.timestamp()


def in_flight(run):
    """A run that has started and has not finished, and that keeps its place on the device: it is on the card, or
    waiting out the program that took it, or coming back from a crash. The queue drains before it fills, so a run three
    hours into a suite is never left half-measured because a model queued behind it happened to be ready. A run parked
    by its own daily window does not hold the card: it is waiting for tomorrow, and the card should go to something
    that can use it tonight. Rows written before the flag existed hold it if they gave way or recovered."""
    flags = run.get("flags") or {}
    if run["status"] in units.ACTIVE:
        return True
    holds = flags.get("holds_card", bool(flags.get("yielded") or flags.get("recovered")))
    return run["status"] == "scheduled" and run.get("started") is not None and bool(holds)


@contextmanager
def one_tick_at_a_time():
    """A tick can now come from the poll, a crashed worker, a wake-up and the end of a run. Two at once could both see
    the card free and start two runs; the one that finds another already working has nothing left to do."""
    paths.DATA.mkdir(parents=True, exist_ok=True)
    with (paths.DATA / "tick.lock").open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def tick(db, moment=None, failed=None):
    """Pauses runs whose window has closed, then starts every due scheduled run whose device is free; returns the
    first one it started. A phone and the card are separate machines, so one never waits for the other. failed names
    the runs systemd has just reported dead, with why, so they are recovered now instead of after a grace period."""
    with one_tick_at_a_time() as held:
        return start_due(db, moment or datetime.now(), failed) if held else None


def start_due(db, moment, failed):
    units.reconcile(db, failed)
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
    if any(run["status"] == "scheduled" or run["status"] in units.ACTIVE for run in store.list_runs(db)):
        arm(db)
    else:
        remove_timer()
    return started
