import json
import time

import pytest

from blackwall import paths, schedule, store, units


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(paths, "DB", tmp_path / "bench.db")
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(schedule.notify, "send", lambda *args, **kwargs: None)
    return store.connect()


def add(db, run_id, status="running", started=None, **flags):
    store.insert_run(db, {"id": run_id, "model": run_id, "suite": "full/v1", "effort": "medium", "status": status,
                          "created": 1.0, "profile": {}, "hardware": {}, "flags": flags})
    store.update_run(db, run_id, started=started if started is not None else time.time() - 900)


def events(run_id, *lines):
    folder = paths.RUNS / run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "events.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))


def test_a_vanished_worker_leaves_the_run_scheduled_where_it_stopped(world):
    db = world
    add(db, "run")
    events("run", {"phase": "supergpqa", "done": 521, "total": 521}, {"phase": "mrcr", "done": 31, "total": 60})
    before = time.time()
    schedule.recover(db, store.get_run(db, "run"))
    run = store.get_run(db, "run")
    assert run["status"] == "scheduled" and run["error"] is None
    assert run["flags"]["recovered"] == 1
    assert run["flags"]["recovered_from"] == "mrcr 31/60"
    assert run["flags"]["parked"] == "recovering after the worker stopped at mrcr 31/60"
    assert before - 1 <= run["flags"]["not_before"] <= time.time() + 1


def crash(db, run_id, cause=None):
    store.update_run(db, run_id, status="running")
    schedule.recover(db, store.get_run(db, run_id), cause)
    return store.get_run(db, run_id)


def answer(run_id, task, count):
    folder = paths.RUNS / run_id
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / f"{task}.jsonl").open("a") as handle:
        handle.write('{"id": "q"}\n' * count)


def test_each_retry_without_progress_waits_longer_and_the_budget_ends_in_a_failure_naming_the_place(world):
    db = world
    add(db, "run")
    events("run", {"phase": "lcb", "done": 30, "total": 101})
    delays = []
    for _ in range(len(schedule.RECOVERY_BACKOFF_S)):
        before = time.time()
        run = crash(db, "run")
        delays.append(round(run["flags"]["not_before"] - before, -1))
    assert delays == [0, 60, 120, 300]
    for _ in range(schedule.RECOVERY_BUDGET - len(schedule.RECOVERY_BACKOFF_S) + 1):
        run = crash(db, "run")
    assert run["status"] == "failed"
    assert "stopped 6 times in a row without a new answer" in run["error"] and "lcb 30/101" in run["error"]


def test_a_worker_that_got_somewhere_before_it_stopped_starts_the_budget_over(world):
    db = world
    add(db, "run")
    events("run", {"phase": "mrcr", "done": 10, "total": 60})
    for round_ in range(schedule.RECOVERY_BUDGET * 2):
        answer("run", "mrcr", 3)
        run = crash(db, "run")
        assert run["status"] == "scheduled" and run["flags"]["recovery_streak"] == 1
        assert run["flags"]["not_before"] <= time.time() + 1
    assert run["flags"]["recovered"] == schedule.RECOVERY_BUDGET * 2


def test_interruptions_that_got_nowhere_are_the_only_ones_that_spend_the_budget(world):
    db = world
    add(db, "run")
    answer("run", "mrcr", 5)
    streaks = []
    for _ in range(2):
        streaks.append(crash(db, "run")["flags"]["recovery_streak"])
    answer("run", "mrcr", 1)
    streaks.append(crash(db, "run")["flags"]["recovery_streak"])
    streaks.append(crash(db, "run")["flags"]["recovery_streak"])
    assert streaks == [1, 2, 1, 2]


def test_the_reason_systemd_gave_is_kept_and_named(world):
    db = world
    add(db, "run")
    events("run", {"phase": "graphwalks", "done": 12, "total": 40})
    run = crash(db, "run", "oom-kill")
    assert run["flags"]["recovered_cause"] == "oom-kill"
    assert run["flags"]["parked"] == "recovering after the worker ran out of memory at graphwalks 12/40"
    assert crash(db, "run", "something-new")["flags"]["parked"] == "recovering after the worker stopped at graphwalks 12/40"


def test_a_run_that_is_no_longer_running_is_not_recovered_twice(world):
    db = world
    add(db, "run")
    assert crash(db, "run")["flags"]["recovered"] == 1
    schedule.recover(db, store.get_run(db, "run"), "signal")
    assert store.get_run(db, "run")["flags"]["recovered"] == 1


def test_recovery_makes_sure_the_tick_unit_exists_to_bring_the_run_back(world, systemd):
    db = world
    add(db, "run")
    crash(db, "run")
    assert any("enable" in command for command in systemd)


def test_a_worker_systemd_reports_dead_is_recovered_at_once_with_the_reason(world, monkeypatch):
    db = world
    monkeypatch.setattr(units, "unit_active", lambda run_id: False)
    add(db, "young", started=time.time() - 5)
    units.reconcile(db)
    assert store.get_run(db, "young")["status"] == "running"
    units.reconcile(db, {"young": "oom-kill"})
    run = store.get_run(db, "young")
    assert run["status"] == "scheduled" and run["flags"]["recovered_cause"] == "oom-kill"


def test_the_failed_unit_systemd_hands_a_tick_names_the_run(world):
    db = world
    add(db, "20261024-flint")
    add(db, "other")
    environment = {"MONITOR_UNIT": "blackwall-20261024-flint.service", "MONITOR_SERVICE_RESULT": "oom-kill"}
    assert units.failed_runs(db, environment) == {"20261024-flint": "oom-kill"}
    assert units.failed_runs(db, {}) == {}
    assert units.failed_runs(db, {"MONITOR_UNIT": "blackwall-tick.service"}) == {}


def test_every_flag_recovery_writes_is_one_resume_clears(world):
    db = world
    add(db, "run")
    flags = crash(db, "run", "oom-kill")["flags"]
    assert set(flags) - {"not_before"} <= set(schedule.TRANSIENT_FLAGS)


def test_a_timer_that_cannot_be_installed_does_not_strand_the_run(world, monkeypatch):
    import subprocess
    db = world
    add(db, "run")

    def refuse():
        raise subprocess.CalledProcessError(1, "systemctl")

    monkeypatch.setattr(schedule, "install_timer", refuse)
    run = crash(db, "run")
    assert run["status"] == "scheduled"
    assert "could not install the schedule timer" in (paths.RUNS / "run" / "worker.log").read_text()
