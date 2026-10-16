from blackwall import board, paths, store, suite


def exported(tmp_path, monkeypatch, site_url):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(paths, "DB", tmp_path / "bench.db")
    monkeypatch.setattr(paths, "SETTINGS", tmp_path / "config.toml")
    db = store.connect()
    store.insert_run(db, {"id": "r", "model": "m", "suite": suite.label("full"), "effort": "max", "status": "complete",
                          "created": 1.0, "finished": 1.0})
    board.export(db, tmp_path / "site", site_url)
    return (tmp_path / "site" / "index.html").read_text()


def test_a_page_with_an_address_names_its_card_and_itself(tmp_path, monkeypatch):
    page = exported(tmp_path, monkeypatch, "https://example.test/bench")
    assert '<meta property="og:image" content="https://example.test/bench/card.png">' in page
    assert '<link rel="canonical" href="https://example.test/bench/">' in page


def test_a_page_without_one_keeps_its_relative_card(tmp_path, monkeypatch):
    page = exported(tmp_path, monkeypatch, None)
    assert '<meta property="og:image" content="card.png">' in page and "canonical" not in page


def test_an_address_is_normalised_and_a_bad_one_is_refused():
    from blackwall import feed
    import pytest

    assert feed.address("https://example.test/bench?x=1#top") == "https://example.test/bench/"
    assert feed.address("http://example.test") == "http://example.test/"
    with pytest.raises(ValueError):
        feed.address("example.test/bench")


def test_a_control_character_in_a_model_name_does_not_break_the_feed():
    import xml.etree.ElementTree as ET
    from blackwall import feed, timeline

    history = timeline.annotate([{"run": "r", "model": "m", "name": "bad\x0bname", "version": "1", "effort": "max",
                                  "finished": 1.0, "index": 50.0, "kind": "full", "suite": "full/v1"}])
    assert ET.fromstring(feed.atom(history, "https://example.test/")).tag.endswith("feed")


def test_feed_links_name_the_model_and_its_effort():
    from blackwall import feed, timeline

    history = timeline.annotate([{"run": "r", "model": "a b", "version": "1", "effort": "max", "finished": 1.0,
                                  "index": 50.0, "kind": "full", "suite": "full/v1"}])
    assert 'href="https://example.test/#a%20b~max"' in feed.atom(history, "https://example.test/")
