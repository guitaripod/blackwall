#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
effort="${1:-max}"
blackwall export --out site >/dev/null
scripts/screenshots.sh site/index.html >/dev/null
cp docs/leaderboard.png docs/leaderboard-dark.png docs/phone.png site/
[[ -f docs/card.png ]] && cp docs/card.png site/
blackwall ls --effort "$effort" --markdown > /tmp/blackwall-readme-table.md
: > /tmp/blackwall-phone-table.md
for phone_effort in "$effort" $(python -c "
import json, pathlib
board = json.loads(pathlib.Path('site/board.json').read_text())
suite = board.get('current') or next(iter(board['suites']))
print(' '.join(board['suites'][suite]['efforts']))
"); do
  blackwall ls --effort "$phone_effort" --device phone --markdown > /tmp/blackwall-phone-table.md 2>/dev/null || true
  [[ -s /tmp/blackwall-phone-table.md ]] && break
done
python - "$effort" <<'PYTHON'
import pathlib, sys
table = pathlib.Path("/tmp/blackwall-readme-table.md").read_text().strip()
readme = pathlib.Path("README.md")
text = readme.read_text()
phone = pathlib.Path("/tmp/blackwall-phone-table.md")
phone_table = phone.read_text().strip() if phone.exists() and phone.read_text().strip() else ""
start, end = "<!--LEADERBOARD-->", "<!--/LEADERBOARD-->"
block = f"{start}\n{table}\n{end}"
if phone_table:
    block = f"{start}\n{table}\n\n### On an iPhone\n\n{phone_table}\n{end}"
if start in text and end in text:
    head, rest = text.split(start, 1)
    text = head + block + rest.split(end, 1)[1]
elif start in text:
    text = text.replace(start, block)
else:
    raise SystemExit("README.md has no <!--LEADERBOARD--> marker")
readme.write_text(text)
print(f"README table refreshed ({sys.argv[1]} effort)")
PYTHON
echo "site/index.html site/card.html site/board.json docs/leaderboard.png docs/leaderboard-dark.png docs/phone.png docs/card.png"
