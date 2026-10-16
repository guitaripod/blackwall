from blackwall import legacy


def test_old_mbench_directories_are_pointed_out_with_the_move(tmp_path, monkeypatch):
    monkeypatch.setattr("blackwall.paths.HOME", tmp_path)
    old, new = tmp_path / ".local/share/mbench", tmp_path / ".local/share/blackwall"
    old.mkdir(parents=True)
    message = legacy.hint([(old, new)])
    assert message.splitlines()[1] == "  mv ~/.local/share/mbench ~/.local/share/blackwall"
    assert "mbench files found" in message


def test_nothing_is_said_once_the_new_directory_exists_or_the_old_never_did(tmp_path):
    old, new = tmp_path / "mbench", tmp_path / "blackwall"
    assert legacy.hint([(old, new)]) is None
    old.mkdir()
    new.mkdir()
    assert legacy.hint([(old, new)] ) is None


def test_every_old_directory_gets_its_own_line(tmp_path):
    pairs = [(tmp_path / f"{name}-old", tmp_path / f"{name}-new") for name in ("data", "config")]
    for old, _ in pairs:
        old.mkdir()
    assert len(legacy.hint(pairs).splitlines()) == 3


def test_the_pairs_name_data_config_and_cache():
    assert [new.name for _, new in legacy.pairs()] == ["blackwall", "blackwall", "blackwall"]
    assert [old.name for old, _ in legacy.pairs()] == ["mbench", "mbench", "mbench"]


def test_a_chosen_data_home_is_not_asked_to_move(monkeypatch):
    monkeypatch.setenv("BLACKWALL_HOME", "/somewhere/else")
    assert all(old.name == "mbench" and old.parent.name != "share" for old, _ in legacy.pairs())


def test_the_data_pair_points_at_wherever_blackwall_keeps_its_data(monkeypatch):
    monkeypatch.delenv("BLACKWALL_HOME", raising=False)
    monkeypatch.setattr("blackwall.paths.DATA", legacy.paths.HOME / "elsewhere")
    assert legacy.pairs()[0][1] == legacy.paths.HOME / "elsewhere"
