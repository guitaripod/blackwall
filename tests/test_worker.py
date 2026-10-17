import urllib.error

import pytest

from blackwall import engine, paths, store, worker


def test_sessions_that_fail_without_gaining_an_answer_are_counted_in_a_row(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(paths, "DB", tmp_path / "bench.db")
    run_dir = tmp_path / "r1"
    run_dir.mkdir()
    (run_dir / "supergpqa.jsonl").write_text("{}\n" * 521)
    (run_dir / "tools.jsonl").write_text("{}\n" * 97)
    (run_dir / "events.jsonl").write_text("{}\n" * 50)
    db = store.connect()
    store.insert_run(db, {"id": "r1", "model": "m", "suite": "full/v1", "status": "running", "flags": {"tasks": ["tools"]}})
    assert worker.answers_kept(run_dir) == 618
    assert [worker.stalled(db, "r1", run_dir) for _ in range(3)] == [1, 2, 3]
    (run_dir / "tools.jsonl").write_text("{}\n" * 98)
    assert worker.stalled(db, "r1", run_dir) == 1
    flags = store.get_run(db, "r1")["flags"]
    assert flags["tasks"] == ["tools"] and flags["stall"] == {"answers": 619, "count": 1}


class FakeHost:
    def __init__(self, outcomes):
        self.outcomes, self.unloaded = list(outcomes), 0

    def ensure_loaded(self):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def unload(self):
        self.unloaded += 1


class FakeEvents:
    def __init__(self):
        self.seen = []

    def emit(self, name, **fields):
        self.seen.append(name)


def refused(code):
    return urllib.error.HTTPError("http://swap/v1", code, "refused", {}, None)


def test_a_refused_load_is_tried_again_after_unloading_everything_else(monkeypatch):
    monkeypatch.setattr(worker, "LOAD_RETRY_PAUSE_S", 0)
    host, events = FakeHost([refused(500), 94.6]), FakeEvents()
    assert worker.loading(host, events) == 94.6
    assert host.unloaded == 1 and events.seen == ["load refused"]


def test_a_load_refused_twice_is_the_server_going_missing(monkeypatch):
    monkeypatch.setattr(worker, "LOAD_RETRY_PAUSE_S", 0)
    host = FakeHost([refused(500), urllib.error.URLError("connection refused")])
    with pytest.raises(engine.ServerGone, match="would not load"):
        worker.loading(host, FakeEvents())


def test_a_client_error_on_load_is_a_real_failure(monkeypatch):
    monkeypatch.setattr(worker, "LOAD_RETRY_PAUSE_S", 0)
    host = FakeHost([refused(404)])
    with pytest.raises(urllib.error.HTTPError):
        worker.loading(host, FakeEvents())
    assert host.unloaded == 0


def test_a_doctor_failure_that_is_a_5xx_is_a_missing_server_not_a_bad_model():
    assert engine.server_error("tool call: a request with tools failed: InternalServerError('Error code: 502')")
    assert not engine.server_error("tool call: calls come back as text")
