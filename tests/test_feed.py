import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from blackwall import feed, timeline

ATOM = "{http://www.w3.org/2005/Atom}"
DAY_ONE = 1_700_000_000.0


def row(run, finished, index=50.0, model="alpha", **fields):
    base = {"run": run, "model": model, "name": model, "effort": "medium", "suite": "full/v1", "version": "1",
            "kind": "full", "finished": finished, "index": index, "lo": None, "hi": None, "decode": None, "peak": None,
            "energyPerCorrect": None, "gpu": None, "driver": None, "build": None}
    return {**base, **fields}


def annotated(*rows):
    return timeline.annotate(list(rows))


def parse(text):
    return ET.fromstring(text)


def day_of(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%d")


def test_the_feed_parses_with_identity_links_and_newest_first():
    history = annotated(row("r1", DAY_ONE, model="alpha"), row("r2", DAY_ONE + 100, model="beta"))
    root = parse(feed.atom(history, "https://example.test/bench"))
    assert root.tag == f"{ATOM}feed"
    assert root.find(f"{ATOM}id").text == "https://example.test/bench/"
    links = {link.get("rel"): link.get("href") for link in root.findall(f"{ATOM}link")}
    assert links["self"] == "https://example.test/bench/feed.xml"
    titles = [entry.find(f"{ATOM}title").text for entry in root.findall(f"{ATOM}entry")]
    assert titles == ["beta: 50.0 quality (debut)", "alpha: 50.0 quality (new best)"]


def test_the_feed_id_is_the_site_url_with_exactly_one_trailing_slash():
    history = annotated(row("r1", DAY_ONE))
    for site_url in ("https://example.test/bench", "https://example.test/bench/", "https://example.test/bench//"):
        assert parse(feed.atom(history, site_url)).find(f"{ATOM}id").text == "https://example.test/bench/"


def test_the_feed_is_limited_to_the_newest_entries():
    history = annotated(row("r1", DAY_ONE), row("r2", DAY_ONE + 1), row("r3", DAY_ONE + 2))
    entries = parse(feed.atom(history, "https://example.test/", limit=2)).findall(f"{ATOM}entry")
    assert [entry.find(f"{ATOM}id").text.rsplit("/", 1)[-1] for entry in entries] == ["r3", "r2"]


def test_the_default_limit_caps_the_feed_at_thirty_entries():
    history = annotated(*(row(f"r{number:02d}", DAY_ONE + number) for number in range(35)))
    assert len(parse(feed.atom(history, "https://example.test/")).findall(f"{ATOM}entry")) == feed.LIMIT == 30


def test_entries_without_a_finish_time_are_left_out_of_the_feed():
    history = annotated(row("unfinished", None), row("done", DAY_ONE))
    entries = parse(feed.atom(history, "https://example.test/")).findall(f"{ATOM}entry")
    assert [entry.find(f"{ATOM}id").text.rsplit("/", 1)[-1] for entry in entries] == ["done"]


def test_an_empty_history_still_gives_a_valid_feed_with_no_entries():
    root = parse(feed.atom([], "https://example.test/"))
    assert root.tag == f"{ATOM}feed"
    assert root.findall(f"{ATOM}entry") == []
    assert root.find(f"{ATOM}updated").text.endswith("Z")


def test_each_entry_id_is_a_tag_uri_built_from_the_host_and_run_id():
    history = annotated(row("run-42", DAY_ONE))
    entry = parse(feed.atom(history, "https://example.test/bench")).find(f"{ATOM}entry")
    assert entry.find(f"{ATOM}id").text == f"tag:example.test,{day_of(DAY_ONE)}:run/run-42"


def test_entry_ids_are_unique_and_identical_across_builds():
    history = annotated(row("r1", DAY_ONE), row("r2", DAY_ONE + 1), row("r3", DAY_ONE + 2))
    first = [entry.find(f"{ATOM}id").text for entry in parse(feed.atom(history, "https://example.test/")).findall(f"{ATOM}entry")]
    second = [entry.find(f"{ATOM}id").text for entry in parse(feed.atom(history, "https://example.test/")).findall(f"{ATOM}entry")]
    assert len(set(first)) == 3
    assert first == second


def test_a_model_name_with_ampersand_and_angle_brackets_round_trips_through_the_parser():
    history = annotated(row("r1", DAY_ONE, model="A & B <Ultra>"))
    text = feed.atom(history, "https://example.test/")
    assert "A &amp; B &lt;Ultra&gt;" in text
    title = parse(text).find(f"{ATOM}entry/{ATOM}title").text
    assert title == "A & B <Ultra>: 50.0 quality (new best)"


def test_title_says_new_best_for_a_record():
    entry = annotated(row("r1", DAY_ONE, model="alpha"))[0]
    assert feed.title_of(entry) == "alpha: 50.0 quality (new best)"


def test_title_says_debut_for_a_first_appearance_that_is_not_a_record():
    entries = annotated(row("r1", DAY_ONE, index=50.0, model="alpha"), row("r2", DAY_ONE + 1, index=40.0, model="beta"))
    assert feed.title_of(entries[1]) == "beta: 40.0 quality (debut)"


def test_title_has_no_note_for_a_plain_repeat():
    entries = annotated(row("r1", DAY_ONE, index=50.0), row("r2", DAY_ONE + 1, index=47.0))
    assert feed.title_of(entries[1]) == "alpha: 47.0 quality"


def test_title_says_measured_without_a_quality_index_when_there_is_none():
    entry = annotated(row("r1", DAY_ONE, index=None))[0]
    assert feed.title_of(entry) == "alpha: measured without a quality index"


def test_title_uses_the_short_name_before_the_middle_dot():
    entry = annotated(row("r1", DAY_ONE, model="alpha", name="alpha · Q8 · 262k"))[0]
    assert feed.title_of(entry) == "alpha: 50.0 quality (new best)"


def test_sentences_give_energy_per_correct_answer_with_a_capital_wh():
    entry = annotated(row("r1", DAY_ONE, energyPerCorrect=0.42))[0]
    assert "0.42 Wh per correct answer" in feed.sentences_of(entry)


def test_sentences_give_a_signed_delta_against_the_previous_run():
    entries = annotated(row("r1", DAY_ONE, index=50.0), row("r2", DAY_ONE + 1, index=50.4))
    assert "+0.4 against its previous run." in feed.sentences_of(entries[1])


def test_sentences_give_a_negative_delta_with_its_sign():
    entries = annotated(row("r1", DAY_ONE, index=50.0), row("r2", DAY_ONE + 1, index=48.8))
    assert "-1.2 against its previous run." in feed.sentences_of(entries[1])


def test_sentences_mark_a_quick_run_as_provisional():
    entry = annotated(row("r1", DAY_ONE, kind="quick", suite="quick/v1"))[0]
    assert "A quick run, ranked as provisional." in feed.sentences_of(entry)


def test_sentences_do_not_call_a_full_run_provisional():
    entry = annotated(row("r1", DAY_ONE))[0]
    assert "provisional" not in feed.sentences_of(entry)
