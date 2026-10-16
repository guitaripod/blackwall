import copy

from blackwall import timeline


def result(run, model, index, finished, version="1", effort="medium"):
    return {"run": run, "model": model, "version": version, "effort": effort, "finished": finished, "index": index}


def marked(entries):
    return {entry["run"]: entry for entry in timeline.annotate(entries)}


def test_the_first_result_of_a_group_is_a_debut_and_a_record():
    found = marked([result("r1", "a", 50.0, 1.0)])["r1"]
    assert found["debut"] is True
    assert found["record"] is True
    assert found["delta"] is None
    assert found["previous"] is None


def test_a_lower_repeat_is_not_a_record_and_moves_by_its_difference_from_the_previous_run():
    found = marked([result("r1", "a", 50.0, 1.0), result("r2", "a", 47.26, 2.0)])
    assert found["r2"]["record"] is False
    assert found["r2"]["debut"] is False
    assert found["r2"]["delta"] == -2.7
    assert found["r2"]["previous"] == "r1"


def test_a_higher_repeat_sets_a_record_and_reports_its_gain():
    found = marked([result("r1", "a", 50.0, 1.0), result("r2", "a", 51.0, 2.0)])
    assert found["r2"]["record"] is True
    assert found["r2"]["delta"] == 1.0
    assert found["r2"]["previous"] == "r1"


def test_a_delta_compares_with_the_models_own_previous_run_not_the_latest_run_of_the_group():
    found = marked([result("r1", "a", 50.0, 1.0), result("r2", "b", 60.0, 2.0), result("r3", "a", 55.0, 3.0)])
    assert found["r3"]["delta"] == 5.0
    assert found["r3"]["previous"] == "r1"
    assert found["r3"]["record"] is False


def test_a_record_belongs_to_the_best_index_of_the_whole_group():
    found = marked([result("r1", "a", 50.0, 1.0), result("r2", "b", 40.0, 2.0), result("r3", "c", 55.0, 3.0)])
    assert found["r2"]["debut"] is True
    assert found["r2"]["record"] is False
    assert found["r3"]["record"] is True


def test_records_are_kept_apart_per_effort_level():
    found = marked([result("r1", "a", 50.0, 1.0, effort="medium"), result("r2", "a", 20.0, 2.0, effort="max"),
                    result("r3", "b", 40.0, 3.0, effort="medium"), result("r4", "b", 30.0, 4.0, effort="max")])
    assert found["r2"]["record"] is True
    assert found["r2"]["debut"] is True
    assert found["r3"]["record"] is False
    assert found["r4"]["record"] is True


def test_records_are_kept_apart_per_suite_version():
    found = marked([result("r1", "a", 50.0, 1.0, version="1"), result("r2", "a", 20.0, 2.0, version="2")])
    assert found["r2"]["record"] is True
    assert found["r2"]["delta"] is None
    assert found["r2"]["previous"] is None


def test_a_debut_is_per_model_version_and_effort():
    found = marked([result("r1", "a", 50.0, 1.0, version="1", effort="medium"),
                    result("r2", "a", 40.0, 2.0, version="1", effort="max"),
                    result("r3", "a", 30.0, 3.0, version="2", effort="medium"),
                    result("r4", "a", 45.0, 4.0, version="1", effort="medium")])
    assert [found[run]["debut"] for run in ("r1", "r2", "r3", "r4")] == [True, True, True, False]


def test_a_run_without_an_index_can_debut_but_never_sets_a_record():
    found = marked([result("r1", "a", None, 1.0)])["r1"]
    assert found["debut"] is True
    assert found["record"] is False
    assert found["delta"] is None


def test_a_run_without_an_index_does_not_move_the_best_so_far():
    found = marked([result("r1", "a", 50.0, 1.0), result("r2", "b", None, 2.0), result("r3", "c", 40.0, 3.0)])
    assert found["r2"]["record"] is False
    assert found["r2"]["delta"] is None
    assert found["r3"]["record"] is False


def test_a_run_without_an_index_is_skipped_when_finding_the_previous_run():
    found = marked([result("r1", "a", 50.0, 1.0), result("r2", "a", None, 2.0), result("r3", "a", 47.26, 3.0)])
    assert found["r2"]["delta"] is None
    assert found["r3"]["delta"] == -2.7
    assert found["r3"]["previous"] == "r1"


def test_input_order_does_not_change_the_annotations():
    entries = [result("r3", "a", 47.26, 3.0), result("r1", "a", 50.0, 1.0), result("r2", "b", 60.0, 2.0),
               result("r4", "b", 58.0, 4.0)]
    assert timeline.annotate(entries) == timeline.annotate(list(reversed(entries)))


def test_results_finishing_together_are_ordered_by_run_id():
    found = marked([result("b", "a", 50.0, 5.0), result("a", "b", 52.0, 5.0)])
    assert found["a"]["record"] is True
    assert found["b"]["record"] is False
    assert found["b"]["debut"] is True
    assert found["b"]["previous"] is None


def test_annotate_returns_new_dicts_and_leaves_the_inputs_untouched():
    entries = [result("r1", "a", 50.0, 1.0), result("r2", "a", 47.26, 2.0)]
    before = copy.deepcopy(entries)
    annotated = timeline.annotate(entries)
    assert entries == before
    assert annotated[0] is not entries[0]
    assert "debut" not in entries[0]


def test_newest_first_orders_by_finish_then_run_id_with_unfinished_last():
    history = [{"run": "a", "finished": 5.0}, {"run": "b", "finished": 9.0}, {"run": "c", "finished": None},
               {"run": "d", "finished": 9.0}]
    assert [entry["run"] for entry in timeline.newest_first(history)] == ["d", "b", "a", "c"]


def test_newest_first_honours_the_limit():
    history = [{"run": str(number), "finished": float(number)} for number in range(5)]
    assert [entry["run"] for entry in timeline.newest_first(history, 2)] == ["4", "3"]
    assert len(timeline.newest_first(history)) == 5
