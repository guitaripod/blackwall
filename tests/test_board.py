import json
import xml.etree.ElementTree as ET
from pathlib import Path

import blackwall
from blackwall import board, paths, store, suite

ATOM = "{http://www.w3.org/2005/Atom}"


def run(model, suite_label, effort, stamp):
    return {"id": f"{model}-{suite_label}-{effort}-{stamp}", "model": model, "suite": suite_label, "effort": effort,
            "created": stamp}


def test_each_effort_is_ranked_on_its_own():
    runs = [run("a", "full/v1", "high", 3), run("a", "full/v1", "medium", 2), run("a", "quick/v1", "medium", 1)]
    assert board.headline(runs, "medium")["a"]["id"] == "a-full/v1-medium-2"
    assert board.headline(runs, "high")["a"]["id"] == "a-full/v1-high-3"
    assert board.headline(runs, "low") == {}


def test_an_older_full_run_beats_a_newer_quick_one():
    runs = [run("a", "quick/v1", "medium", 5), run("a", "full/v1", "medium", 4)]
    assert board.headline(runs, "medium")["a"]["suite"] == "full/v1"


def test_smoke_runs_never_rank_and_missing_effort_means_medium():
    runs = [run("a", "smoke/v1", "medium", 9), {**run("b", "quick/v1", None, 1), "effort": None}]
    chosen = board.headline(runs, "medium")
    assert "a" not in chosen
    assert chosen["b"]["suite"] == "quick/v1"


def test_runs_of_unknown_suite_versions_stay_off_the_board(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(paths, "DB", tmp_path / "bench.db")
    db = store.connect()
    for model, label, created in (("a", "full/v9", 1.0), ("a", suite.label("full"), 2.0), ("b", "full/v9", 3.0)):
        store.insert_run(db, {"id": f"{model}-{label}", "model": model, "suite": label, "effort": "medium",
                              "status": "complete", "created": created, "finished": created})
    store.set_metrics(db, f"a-{suite.label('full')}", {"supergpqa.score": {"value": 50.0}, "mrcr.bin.16384": {"value": 90.0}})
    data = board.collect(db)
    assert set(data["suites"]) == {suite.VERSION}
    ranked = data["suites"][suite.VERSION]["rankings"]["medium"]
    assert [model["id"] for model in ranked] == ["a"]
    assert ranked[0]["tasks"]["supergpqa"]["value"] == 50.0 and ranked[0]["tasks"].get("mrcr") is None
    assert data["rankings"] == data["suites"][suite.VERSION]["rankings"]


def test_task_entries_carry_their_breakdown():
    metrics = {"mrcr.score": {"value": 60.0}, "mrcr.bin.16384": {"value": 90.0}, "mrcr.bin.131072": {"value": 20.0},
               "mrcr.unreachable": {"value": 5.0}}
    entry = board.task_entry(metrics, "mrcr")
    assert entry["parts"] == {"16384": 90.0, "131072": 20.0}
    assert entry["unreachable"] == 5.0


def test_warnings_say_what_a_context_cap_cost():
    tasks = {"mrcr": {"unreachable": 25.0}, "graphwalks": {"unreachable": 0.0}, "math": {}}
    warnings = board.warnings_for(tasks, {"context": 65536}, {"mrcr": "MRCR 8-needle", "graphwalks": "Graphwalks"})
    assert warnings == ["Capped at 64k tokens per request: MRCR 8-needle 25% out of reach"]
    assert board.warnings_for({"math": {}}, {}, {}) == []


def test_export_writes_a_page_and_its_data(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(paths, "DB", tmp_path / "bench.db")
    db = store.connect()
    store.insert_run(db, {"id": "r", "model": "m", "suite": suite.label("full"), "effort": "max", "status": "complete",
                          "created": 1.0, "finished": 1.0})
    written = board.export(db, tmp_path / "site")
    assert [path.name for path in written] == ["index.html", "card.html", "board.json"]
    page = (tmp_path / "site" / "index.html").read_text()
    assert "/*__DATA__*/null" not in page and '"suites"' in page
    card = (tmp_path / "site" / "card.html").read_text()
    assert "/*__DATA__*/null" not in card and '"rankings"' in card
    assert json.loads((tmp_path / "site" / "board.json").read_text())["current"] == suite.VERSION


def test_the_published_board_is_the_cards_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(paths, "DB", tmp_path / "bench.db")
    db = store.connect()
    for model, hardware in (("card", {"gpu": "RTX PRO 6000"}), ("air", {"class": "phone", "device": "iPhone Air"})):
        store.insert_run(db, {"id": model, "model": model, "suite": suite.label("full"), "effort": "max",
                              "status": "complete", "created": 1.0, "finished": 1.0, "hardware": hardware})
    everything = board.collect(db)["rankings"]["max"]
    published = board.collect(db, board.PUBLISHED_CLASSES)["rankings"]["max"]
    assert {model["id"] for model in everything} == {"card", "air"}
    assert [model["id"] for model in published] == ["card"]
    board.export(db, tmp_path / "site")
    assert "iPhone Air" not in (tmp_path / "site" / "board.json").read_text()


def connected(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(paths, "DB", tmp_path / "bench.db")
    return store.connect()


def finished_run(db, run_id, model, suite_label, finished, status="complete", hardware=None):
    fields = {"id": run_id, "model": model, "suite": suite_label, "effort": "medium", "status": status,
              "created": finished, "finished": finished}
    if hardware is not None:
        fields["hardware"] = hardware
    store.insert_run(db, fields)


def test_collect_publishes_the_schema_generator_and_history_entries(monkeypatch, tmp_path):
    db = connected(monkeypatch, tmp_path)
    finished_run(db, "r1", "alpha", suite.label("full"), 10.0)
    store.set_metrics(db, "r1", {"index.quality": {"value": 50.0, "lo": 48.0, "hi": 52.0},
                                 "speed.decode": {"value": 120.0}, "energy.per_correct": {"value": 0.42}})
    data = board.collect(db)
    assert data["schema"] == board.SCHEMA
    assert data["generator"] == {"name": "blackwall", "version": blackwall.__version__}
    assert "database" not in data
    entry = data["history"][0]
    assert {"run", "model", "effort", "version", "index", "lo", "hi", "decode", "record", "debut", "delta"} <= set(entry)
    assert (entry["run"], entry["model"], entry["effort"], entry["version"]) == ("r1", "alpha", "medium", suite.VERSION)
    assert (entry["index"], entry["lo"], entry["hi"], entry["decode"]) == (50.0, 48.0, 52.0, 120.0)
    assert entry["record"] is True and entry["debut"] is True and entry["delta"] is None


def test_history_lists_only_complete_full_and_quick_runs(monkeypatch, tmp_path):
    db = connected(monkeypatch, tmp_path)
    finished_run(db, "full", "alpha", suite.label("full"), 10.0)
    finished_run(db, "quick", "alpha", suite.label("quick"), 11.0)
    finished_run(db, "phone", "alpha", "phone/v1", 12.0)
    finished_run(db, "unfinished", "alpha", suite.label("full"), 13.0, status="running")
    history = board.collect(db)["history"]
    assert [entry["run"] for entry in history] == ["full", "quick"]


def test_the_published_history_leaves_out_phone_class_runs(monkeypatch, tmp_path):
    db = connected(monkeypatch, tmp_path)
    finished_run(db, "card", "card", suite.label("full"), 10.0)
    finished_run(db, "air", "air", suite.label("full"), 11.0, hardware={"class": "phone", "device": "iPhone Air"})
    assert [entry["run"] for entry in board.collect(db)["history"]] == ["card", "air"]
    assert [entry["run"] for entry in board.collect(db, board.PUBLISHED_CLASSES)["history"]] == ["card"]


def test_export_without_a_site_url_writes_the_page_and_json_only(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "SETTINGS", tmp_path / "absent.toml")
    db = connected(monkeypatch, tmp_path)
    finished_run(db, "r1", "alpha", suite.label("full"), 10.0)
    written = board.export(db, tmp_path / "site")
    assert sorted(path.name for path in written) == ["board.json", "card.html", "index.html"]
    assert sorted(path.name for path in (tmp_path / "site").iterdir()) == ["board.json", "card.html", "index.html"]
    published = json.loads((tmp_path / "site" / "board.json").read_text())["published"]
    assert published == {"json": "board.json", "feed": None}


def test_export_with_a_site_url_adds_a_feed_that_parses(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "SETTINGS", tmp_path / "absent.toml")
    db = connected(monkeypatch, tmp_path)
    finished_run(db, "r1", "alpha", suite.label("full"), 10.0)
    written = board.export(db, tmp_path / "site", "https://example.test/bench")
    assert [path.name for path in written] == ["index.html", "card.html", "board.json", "feed.xml"]
    published = json.loads((tmp_path / "site" / "board.json").read_text())["published"]
    assert published == {"json": "board.json", "feed": "feed.xml"}
    root = ET.parse(tmp_path / "site" / "feed.xml").getroot()
    assert root.tag == f"{ATOM}feed"
    assert len(root.findall(f"{ATOM}entry")) == 1


def test_export_takes_the_feed_address_from_config_toml(monkeypatch, tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('site_url = "https://example.test/x/"\n')
    monkeypatch.setattr(paths, "SETTINGS", config)
    db = connected(monkeypatch, tmp_path)
    finished_run(db, "r1", "alpha", suite.label("full"), 10.0)
    board.export(db, tmp_path / "site")
    root = ET.parse(tmp_path / "site" / "feed.xml").getroot()
    assert root.find(f"{ATOM}id").text == "https://example.test/x/"


def test_publishable_replaces_the_home_directory_with_a_tilde(monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/home/someone")))
    text = board.publishable({"path": "/home/someone/models/a.gguf"})
    assert "/home/someone" not in text
    assert json.loads(text) == {"path": "~/models/a.gguf"}
