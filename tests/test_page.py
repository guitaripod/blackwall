import json
from pathlib import Path

import pytest

from blackwall import board, paths, store, suite

TASKS = ("supergpqa", "math", "lcb", "mrcr", "graphwalks", "tools")
SCORES = {
    "alpha": {"supergpqa": 70, "math": 80, "lcb": 40, "mrcr": 90, "graphwalks": 85, "tools": 50, "decode": 150, "wh": 2.0},
    "bravo": {"supergpqa": 45, "math": 60, "lcb": 85, "mrcr": 30, "graphwalks": 70, "tools": 95, "decode": 210, "wh": 4.0},
    "charlie": {"supergpqa": 55, "math": 65, "lcb": 60, "mrcr": 40, "graphwalks": 60, "tools": 80, "decode": 180, "wh": 3.0},
}


def finished_metrics(scores):
    metrics = {}
    for task in TASKS:
        value = scores[task]
        metrics[f"{task}.score"] = {"value": value, "unit": "%", "n": 60, "lo": value - 6, "hi": value + 6}
        metrics[f"{task}.tokens"] = {"value": 4000.0}
        metrics[f"{task}.truncated"] = {"value": 3.0}
    metrics["mrcr.bin.16384"] = {"value": scores["mrcr"] + 5}
    metrics["mrcr.bin.131072"] = {"value": scores["mrcr"] - 5}
    groups = [scores["supergpqa"], scores["math"], scores["lcb"], (scores["mrcr"] + scores["graphwalks"]) / 2, scores["tools"]]
    mean = sum(groups) / len(groups)
    metrics["index.quality"] = {"value": mean, "unit": "%", "n": 5, "lo": mean - 3, "hi": mean + 3}
    metrics["speed.decode"] = {"value": scores["decode"], "unit": "tok/s", "n": 3}
    metrics["speed.peak"] = {"value": scores["decode"] * 2.5, "unit": "tok/s", "n": 2}
    metrics["speed.conc.1"] = {"value": scores["decode"], "unit": "tok/s", "n": 2}
    metrics["speed.conc.4"] = {"value": scores["decode"] * 2.5, "unit": "tok/s", "n": 2}
    metrics["speed.ttft.32000"] = {"value": 3.0, "unit": "s", "n": 2}
    metrics["energy.per_correct"] = {"value": scores["wh"], "unit": "Wh", "n": 100}
    return metrics


@pytest.fixture
def database(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(paths, "DB", tmp_path / "bench.db")
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    db = store.connect()
    for stamp, (model, scores) in enumerate(SCORES.items(), start=1):
        run_id = f"{model}-run"
        store.insert_run(db, {"id": run_id, "model": model, "name": f"{model.title()} 7B · test · Q4", "suite": suite.label("full"),
                              "effort": "max", "status": "complete", "created": float(stamp), "finished": 1790000000.0 + stamp * 86400,
                              "profile": {"engine": "llama.cpp", "quantization": "Q4", "context": 65536},
                              "flags": {"effort_level": "max"}})
        store.set_metrics(db, run_id, finished_metrics(scores))
    store.insert_run(db, {"id": "delta-run", "model": "delta", "name": "Delta 9B · test · Q4", "suite": suite.label("full"),
                          "effort": "max", "status": "running", "created": 9.0, "started": 9.0,
                          "profile": {"engine": "llama.cpp", "quantization": "Q4", "context": 65536},
                          "flags": {"effort_level": "max", "tasks": ["speed", *suite.QUALITY_TASKS]}})
    store.set_metrics(db, "delta-run", {"supergpqa.score": {"value": 60.0, "unit": "%", "n": 60, "lo": 54, "hi": 66},
                                       "speed.decode": {"value": 120.0, "unit": "tok/s", "n": 3}})
    run_dir = paths.RUNS / "delta-run"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").write_text(json.dumps({"t": 1.0, "phase": "math", "done": 30, "total": 126}) + "\n")
    return db


def test_a_run_in_progress_is_in_the_data_with_its_progress(database):
    data = board.collect(database)
    [live] = data["live"]
    assert live["id"] == "delta" and live["index"] is None and live["run"]["finished"] is None
    assert live["tasks"]["supergpqa"]["value"] == 60.0
    assert live["progress"]["current"] == {"task": "math", "done": 30, "total": 126}
    assert live["progress"]["plan"][0] == "speed"
    assert sorted(model["id"] for model in data["rankings"]["max"]) == ["alpha", "bravo", "charlie"]


def test_finished_and_queued_runs_are_not_live(database):
    store.insert_run(database, {"id": "echo-run", "model": "echo", "suite": suite.label("full"), "effort": "max", "status": "failed"})
    assert [entry["id"] for entry in board.collect(database)["live"]] == ["delta"]


def test_the_plain_table_names_every_ranked_model_best_first(database):
    table = board.plain_table(board.collect(database))
    assert table.startswith("<noscript>") and table.endswith("</noscript>")
    assert table.index("Bravo") < table.index("Alpha") < table.index("Charlie")
    assert "Delta" not in table


def test_the_page_keeps_what_export_needs(database):
    html = board.page(board.collect(database))
    assert html.count('<meta property="og:image" content="card.png">') == 1
    assert "/*__DATA__*/null" not in html and "<!--__NOSCRIPT__-->" not in html
    assert '"live"' in html and "<noscript>" in html


playwright = pytest.importorskip("playwright.sync_api")


def installed_chromium():
    """Any headless Chromium Playwright has already downloaded, for when the library asks for a build this machine lacks."""
    found = sorted((Path.home() / ".cache" / "ms-playwright").glob("chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"))
    return str(found[-1]) if found else None


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as driver:
        try:
            chromium = driver.chromium.launch()
        except Exception as error:
            fallback = installed_chromium()
            if not fallback:
                pytest.skip(f"no Chromium to drive: {error}")
            chromium = driver.chromium.launch(executable_path=fallback)
        yield chromium
        chromium.close()


@pytest.fixture
def page_file(database, tmp_path):
    data = board.collect(database)
    data["published"] = {"json": "board.json", "feed": None}
    path = tmp_path / "board.html"
    path.write_text(board.page(data))
    return path.as_uri()


@pytest.fixture
def card_file(database, tmp_path):
    path = tmp_path / "card.html"
    path.write_text(board.page(board.collect(database), board.CARD))
    return path.as_uri()


def open_page(browser, url, width=1400, height=900, scheme="dark", suffix=""):
    context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, reduced_motion="reduce",
                                  is_mobile=width < 500, has_touch=width < 500)
    errors = []
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.goto(url + suffix)
    page.wait_for_selector(".row-wrap")
    return context, page, errors


def test_the_page_renders_clean_and_fits_at_desktop_and_phone_width(browser, page_file):
    for width in (1400, 390):
        context, page, errors = open_page(browser, page_file, width=width)
        assert errors == []
        assert page.locator(".row-wrap").count() == 4
        assert page.locator(".row-wrap.ghost-row").count() == 1
        assert page.evaluate("document.documentElement.scrollWidth") <= page.evaluate("document.documentElement.clientWidth")
        context.close()


def test_the_verdict_and_cards_say_who_leads(browser, page_file):
    context, page, errors = open_page(browser, page_file)
    assert page.locator(".verdict .headline").inner_text().strip() != ""
    labels = page.locator(".card .k").all_text_contents()
    assert {"Smartest", "Fastest", "Leanest", "On the bench now"} <= set(labels)
    assert errors == []
    context.close()


def test_opening_a_model_shows_its_profile_and_charts(browser, page_file):
    context, page, errors = open_page(browser, page_file)
    page.click('.row-wrap[data-id="bravo"] .name')
    page.wait_for_selector(".row-wrap.open .profile")
    profile = page.locator(".row-wrap.open .profile")
    assert "Where it is strong and weak" in profile.text_content()
    assert "Reproduce" in profile.text_content()
    page.click(".row-wrap.open summary")
    assert page.locator(".row-wrap.open .ladder").count() >= 2
    assert errors == []
    context.close()


def test_weights_rerank_the_table_and_say_who_moved(browser, page_file):
    context, page, errors = open_page(browser, page_file)
    first = page.locator(".row-wrap").first.get_attribute("data-id")
    page.click("#lab-toggle")
    page.click('[data-preset="chat"]')
    page.wait_for_timeout(100)
    assert page.locator(".row-wrap").first.get_attribute("data-id") != first
    assert "moves from" in page.locator("#lab-msg").inner_text()
    assert page.locator(".delta").count() >= 1
    page.click("#lab-reset")
    assert page.locator(".row-wrap").first.get_attribute("data-id") == first
    assert errors == []
    context.close()


def test_comparing_two_models_writes_a_sentence_that_respects_the_error_bars(browser, page_file):
    context, page, errors = open_page(browser, page_file)
    page.click('.row-wrap[data-id="alpha"] [data-pin]')
    page.click('.row-wrap[data-id="bravo"] [data-pin]')
    page.wait_for_selector(".dock.show .h2h")
    sentence = page.locator(".dock .sent").first.inner_text()
    assert "clearly leads on" in sentence or "leads nowhere clearly" in sentence
    assert "Overall it is ahead in" in sentence
    assert errors == []
    context.close()


def test_the_cost_view_swaps_the_columns(browser, page_file):
    context, page, errors = open_page(browser, page_file)
    page.click('[data-columns="cost"]')
    headers = page.locator("#hrow").text_content()
    assert "Peak tok/s" in headers and "Wh / correct" in headers and "Knowledge" not in headers
    assert errors == []
    context.close()


def test_the_address_opens_a_model_and_follows_the_page(browser, page_file):
    context, page, errors = open_page(browser, page_file, suffix="#bravo~max")
    assert page.locator('.row-wrap[data-id="bravo"].open').count() == 1
    page.click("#lab-toggle")
    page.click('[data-preset="docs"]')
    assert "w=" in page.evaluate("location.hash")
    address = page.evaluate("location.href")
    assert errors == []
    context.close()
    context, page, errors = open_page(browser, address)
    assert page.locator('.row-wrap[data-id="bravo"].open').count() == 1
    assert page.locator("#lab-toggle").inner_text() == "Weights: custom"
    assert errors == []
    context.close()


def test_the_command_palette_jumps_and_switches(browser, page_file):
    context, page, errors = open_page(browser, page_file)
    page.keyboard.press("Control+k")
    page.fill("#pal-q", "energy")
    page.keyboard.press("Enter")
    assert page.locator('[data-axis="wh"][aria-pressed="true"]').count() == 1
    assert errors == []
    context.close()


def body_channels(page):
    background = page.evaluate("getComputedStyle(document.body).backgroundColor")
    return [int(part) for part in background.removeprefix("rgb(").removesuffix(")").split(",")[:3]]


def test_the_page_stays_dark_until_the_toggle_picks_light_and_remembers_it(browser, page_file):
    context, page, errors = open_page(browser, page_file, scheme="light")
    assert max(body_channels(page)) < 40
    page.click("#theme")
    assert min(body_channels(page)) > 200
    page.reload()
    page.wait_for_selector(".row-wrap")
    assert min(body_channels(page)) > 200
    page.click("#theme")
    assert max(body_channels(page)) < 40
    assert errors == []
    context.close()


def test_a_board_with_no_runs_says_so_and_stays_quiet(browser, monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(paths, "DB", tmp_path / "bench.db")
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    path = tmp_path / "empty.html"
    path.write_text(board.page(board.collect(store.connect())))
    context = browser.new_context(viewport={"width": 1200, "height": 800})
    errors = []
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(path.as_uri())
    page.wait_for_selector("#empty:not([hidden])")
    assert "No finished runs yet" in page.locator("#empty").text_content()
    assert not page.locator("#board-block").is_visible()
    assert errors == []
    context.close()


def test_a_model_scored_without_timing_is_listed_but_not_plotted(browser, database, tmp_path):
    untimed = {task: 50 for task in TASKS}
    metrics = finished_metrics({**untimed, "decode": 100, "wh": 1.0})
    for key in [key for key in metrics if key.startswith(("speed.", "energy."))]:
        del metrics[key]
    store.insert_run(database, {"id": "echo-run", "model": "echo", "name": "Echo 3B · test · Q4", "suite": suite.label("full"),
                                "effort": "max", "status": "complete", "created": 7.0, "finished": 1790500000.0,
                                "profile": {"engine": "llama.cpp", "quantization": "Q4"}, "flags": {"effort_level": "max"}})
    store.set_metrics(database, "echo-run", metrics)
    data = board.collect(database)
    path = tmp_path / "untimed.html"
    path.write_text(board.page(data))
    context, page, errors = open_page(browser, path.as_uri())
    assert page.locator('.row-wrap[data-id="echo"]').count() == 1
    assert page.locator('#plot .pt[data-id="echo"]').count() == 0
    assert "not plotted" in page.locator("#legend").text_content()
    assert errors == []
    context.close()


def lit_pixels(page, x, y, width, height):
    return page.evaluate(
        """([x, y, width, height]) => {
            const data = document.getElementById("card").getContext("2d").getImageData(x, y, width, height).data;
            let lit = 0;
            for (let i = 0; i < data.length; i += 4) if (data[i] + data[i + 1] + data[i + 2] > 600) lit += 1;
            return lit;
        }""",
        [x, y, width, height],
    )


def test_the_share_card_opens_on_the_wall_and_draws_the_wordmark(browser, card_file):
    context = browser.new_context(viewport={"width": 1200, "height": 675})
    errors = []
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(card_file + "?bare=1")
    page.wait_for_function("document.getElementById('show').value === 'wall'")
    assert "show=wall" in page.evaluate("location.hash")
    assert lit_pixels(page, 112, 150, 2176, 260) > 20000
    assert errors == []
    context.close()


def test_a_share_link_that_names_its_models_keeps_its_own_card(browser, card_file):
    context = browser.new_context(viewport={"width": 1200, "height": 675})
    page = context.new_page()
    page.goto(card_file + "?bare=1#show=two")
    page.wait_for_function("document.getElementById('show').value === 'two'")
    assert lit_pixels(page, 112, 150, 2176, 260) < 20000
    context.close()
