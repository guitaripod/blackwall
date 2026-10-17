# Changelog

All notable changes to Blackwall are listed here, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow [Semantic Versioning](https://semver.org/). The published `board.json` carries its own `schema` number, described in [docs/data.md](docs/data.md).

## [2.0.3] - 2026-10-17

The RAM safety stop no longer fires on a dip of a few seconds. What is measured and the `board.json` schema are unchanged.

### Fixed
- **A short dip in free RAM no longer unloads the model.** The guard checked once every five seconds and unloaded the model the first time free RAM was under 8 GB. A run on a busy desktop was stopped seven times in a day by dips that were over in seconds (a compile, a browser), each one costing every request in flight and a reload. Free RAM now has to stay under the floor for 45 seconds before the run stops.
- **A memory stop is retried within minutes, not after ten.** The cause is over long before that, and the next session waits for room anyway. A run that stopped for memory no longer counts toward the same-questions-failed limit either.

### Added
- **Dips are written down with their cause.** The first reading of every dip records the programs holding the most memory (processes of one name summed) as a `memory low` event in the run's log, so the next stop names what caused it.

## [2.0.2] - 2026-10-17

A run no longer fails for good when its server goes missing while loading. What is measured and the `board.json` schema are unchanged.

### Fixed
- **A refused load is tried again, then waited out.** When llama-swap answers a load with a 5xx, because the model did not start (small models a client keeps loading held the VRAM), Blackwall unloads everything else and loads once more. A second refusal counts as the server going missing: the run gives way and tries again later, and fails only after the same stall limit as a server that dies mid-task.
- **A 5xx in the preflight check is a missing server, not a bad model.** The tool-call check of a model whose server vanished under it used to fail the run for good, with hours of answers saved.

### Board
- Nemotron 3.5 Super VL 120B (vLLM, NVFP4, MTP) joins the max-effort board.

## [2.0.1] - 2026-10-17

A cleanup release. What is measured, the scores and the `board.json` schema are unchanged.

### Changed
- **Leaner page and card.** The leaderboard page and the share card lose their phone-only code (class tabs, verdicts, thermal and battery columns), which the published board could no longer reach. What they render is unchanged, and share links no longer carry a stray `class=null`.
- **Plainer notes.** A ranking that spans two drivers on one card now says "2 drivers on one NVIDIA RTX PRO 6000 Blackwell" and names each by driver, in the terminal and in the README table.
- **`blackwall -h` lists every command**, and its examples show `export --site-url`.
- **The page footer** no longer claims the site is rebuilt after every run, which only the local page is.
- **Notifications and help text** write the name as Blackwall.
- **`scripts/publish.sh`** takes `SITE_URL` for the address the feed is built for.

### Documentation
- The README is tighter, its command list is aligned, and it covers `config.toml`, `hardware.json` and the phone note in one place each.
- `docs/data.md` describes every key of a model entry, including `fingerprint`, `repeats` and the phone-run fields.

## [2.0.0] - 2026-10-17

The first release as Blackwall: the benchmark for one NVIDIA RTX PRO 6000 Blackwell. It continues the mbench 1.x line under a new name, so the command, the data directory and the environment variables changed.

### Added
- **The wall over time.** A chart of the best quality index so far against the date each run finished, and a list of recent results that says which ones were a debut, a new best, or a move from the model's previous run.
- **An Atom feed.** `blackwall export --site-url URL` (or `site_url` in `config.toml`) writes `feed.xml` next to the page, one entry per finished run, with ids that never change.
- **`board.json` schema 1.** It carries `schema`, `generator`, a `history` of every finished run and a `published` block. Keys are only ever added; a breaking change bumps `schema`.
- **Deep links.** `#<model id>~<effort>` opens the page on that model at that effort (the effort is optional), and the address follows what you open.
- **A "Follow the board" section** on the published page, linking the feed, the data and the releases.
- **Link previews.** An exported page with an address names its share card and itself absolutely, which is what link previews follow.
- **A migration hint.** If mbench's directories are still there, every command says which `mv` moves each one.
- **A release workflow.** Pushing a version tag runs the tests, builds the wheel and sdist, and publishes a GitHub release with the notes from this file.

### Changed
- **Name.** The package, the command (`blackwall`), `~/.local/share/blackwall`, `~/.config/blackwall`, `~/.cache/blackwall`, the `BLACKWALL_*` environment variables, the `blackwall-tick` timer, the `blackwall-<run>` units and the `blackwall-lcb-grader` image all follow.
- **Look.** Black and NVIDIA green, a wall cut through the wordmark, chamfered panels, and a share card to match. The page is dark only.
- **The published board is the card's alone.** Phone runs stay in the database and in `blackwall ls --device phone`; their documentation moved to [docs/phone.md](docs/phone.md).
- **The page opens on the effort with the most timed models**, not always on medium.
- **Rows name only what differs.** When a ranking spans two drivers, a row says `driver 610.57.04` instead of repeating the card's name.
- **The wall is a list as well as a line**, beside the quality-against-speed chart.
- **The version lives in one place**, `blackwall/__init__.py`, and the build reads it from there.
- **Published JSON no longer names the machine.** The home directory is written `~`, and the `database` key is gone.

### Removed
- The light theme and the phone tab on the published page.

### Migrating from mbench
```
mv ~/.local/share/mbench ~/.local/share/blackwall
mv ~/.config/mbench ~/.config/blackwall
mv ~/.cache/mbench ~/.cache/blackwall
uv tool uninstall mbench && uv tool install git+https://github.com/guitaripod/blackwall
```
Rename `MBENCH_*` variables in your shell to `BLACKWALL_*`, and the `mbench-tick` timer is replaced the next time you schedule a run.

## Before 2.0

Versions 1.6.2 to 1.7.1 were released as mbench; their notes are on the [releases page](https://github.com/guitaripod/blackwall/releases).
