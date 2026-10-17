#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 prep.py "${1:-}"
python3 - <<'PY'
import pathlib
here = pathlib.Path(".")
page = (here / "page.html").read_text().replace("/*DATA*/null", (here / "data.json").read_text())
(here / "index.html").write_text(page)
print("index.html", len(page), "bytes")
PY
