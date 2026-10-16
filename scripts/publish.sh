#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
effort="${1:-max}"
blackwall export --out site >/dev/null
scripts/screenshots.sh site/index.html >/dev/null
cp docs/banner.png docs/leaderboard.png site/
[[ -f docs/card.png ]] && cp docs/card.png site/
blackwall ls --effort "$effort" --markdown > /tmp/blackwall-readme-table.md
python - "$effort" <<'PYTHON'
import pathlib, sys
table = pathlib.Path("/tmp/blackwall-readme-table.md").read_text().strip()
readme = pathlib.Path("README.md")
text = readme.read_text()
start, end = "<!--LEADERBOARD-->", "<!--/LEADERBOARD-->"
block = f"{start}\n{table}\n{end}"
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
echo "site/index.html site/card.html site/board.json docs/banner.png docs/leaderboard.png docs/card.png"
