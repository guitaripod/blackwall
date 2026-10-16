#!/usr/bin/env python3
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def notes_for(version, text):
    """The body of one version's section in the changelog, the words a release page shows. A version with no section is a
    release nobody wrote down, which is worth stopping for."""
    section = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not section or not section.group(1).strip():
        raise SystemExit(f"CHANGELOG.md has no notes for {version}")
    return section.group(1).strip() + "\n"


if __name__ == "__main__":
    sys.stdout.write(notes_for(sys.argv[1], CHANGELOG.read_text()))
