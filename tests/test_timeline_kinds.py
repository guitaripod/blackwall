from blackwall import timeline


def entry(run, index, finished, kind="full", model="m", effort="max"):
    return {"run": run, "model": model, "version": "1", "effort": effort, "finished": finished, "index": index, "kind": kind}


def test_a_quick_run_can_debut_but_never_sets_a_record():
    marks = {item["run"]: item for item in timeline.annotate([entry("q", 70, 1, kind="quick")])}
    assert marks["q"]["debut"] and not marks["q"]["record"]


def test_a_full_run_after_a_quick_one_is_the_record_and_has_nothing_to_move_from():
    marks = {item["run"]: item for item in timeline.annotate([entry("q", 70, 1, kind="quick"), entry("f", 50, 2)])}
    assert marks["f"]["record"] and not marks["f"]["debut"]
    assert marks["f"]["delta"] is None and marks["f"]["previous"] is None


def test_a_repeat_is_compared_with_the_previous_run_of_its_own_kind():
    marks = {item["run"]: item for item in timeline.annotate(
        [entry("f1", 50, 1), entry("q", 90, 2, kind="quick"), entry("f2", 52, 3)])}
    assert marks["f2"]["delta"] == 2.0 and marks["f2"]["previous"] == "f1"


def test_a_quick_run_does_not_raise_the_bar_for_full_runs():
    marks = {item["run"]: item for item in timeline.annotate(
        [entry("q", 90, 1, kind="quick", model="a"), entry("f", 60, 2, model="b")])}
    assert marks["f"]["record"]


def test_a_zero_limit_gives_no_entries():
    assert timeline.newest_first([entry("a", 1, 1)], 0) == []
    assert len(timeline.newest_first([entry("a", 1, 1)])) == 1
