import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "release-notes.py"
spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)

LOG = "# Changelog\n\n## [2.0.0] - 2026-10-17\n\nIntro.\n\n### Added\n- one\n\n## [1.9.0] - 2026-01-01\n\n- older\n"


def test_a_versions_notes_stop_at_the_next_heading():
    notes = release_notes.notes_for("2.0.0", LOG)
    assert notes.startswith("Intro.") and "- one" in notes and "older" not in notes


def test_the_last_section_runs_to_the_end():
    assert release_notes.notes_for("1.9.0", LOG) == "- older\n"


def test_a_version_nobody_wrote_down_stops_the_release():
    with pytest.raises(SystemExit):
        release_notes.notes_for("3.0.0", LOG)


def test_the_real_changelog_has_notes_for_the_current_version():
    import blackwall

    text = (SCRIPT.parent.parent / "CHANGELOG.md").read_text()
    assert release_notes.notes_for(blackwall.__version__, text)
