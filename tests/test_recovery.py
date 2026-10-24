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
    monkeypatch.setattr(schedule, "arm_wake", lambda seconds, run_id: None)
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


def test_each_retry_waits_longer_and_the_budget_ends_in_a_failure_naming_the_place(world):
    db = world
    add(db, "run")
    events("run", {"phase": "lcb", "done": 30, "total": 101})
    run = store.get_run(db, "run")
    delays = []
    for _ in range(len(schedule.RECOVERY_BACKOFF_S)):
        before = time.time()
        schedule.recover(db, run)
        run = store.get_run(db, "run")
        delays.append(round(run["flags"]["not_before"] - before, -1))
    assert delays == [0, 60, 120, 300]
    for _ in range(schedule.RECOVERY_BUDGET):
        schedule.recover(db, run)
        run = store.get_run(db, "run")
    assert run["status"] == "failed"
    assert "stopped 6 times" in run["error"] and "lcb 30/101" in run["error"]


def test_a_recovered_run_keeps_the_card_while_it_comes_back(world):
    db = world
    add(db, "flint", started=time.time() - 900)
    schedule.recover(db, store.get_run(db, "flint"))
    assert schedule.in_flight(store.get_run(db, "flint"))
    add(db, "next", status="scheduled", started=None)
    assert schedule.in_flight(store.get_run(db, "next")) is False
