import html
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, feed
from . import metrics as scores
from . import doctor, notify, paths, stack, store, suite, timeline, units

KINDS = ("full", "quick", "phone")
PUBLISHED_CLASSES = (units.GPU_CLASS,)
SCHEMA = 1
HISTORY_KINDS = suite.QUALITY_SUITES
EFFORT_ORDER = ("medium", "max", "high", "xhigh", "low", "min", "minimal", "none")
DEFAULT_EFFORT = "medium"
TEMPLATE = paths.PACKAGE / "templates" / "leaderboard.html"
CARD = paths.PACKAGE / "templates" / "card.html"
PART_PREFIXES = (".bin.", ".part.")
LIVE_STATUSES = ("running", "scheduled")
REBUILD_TIMEOUT_S = 300


def kind_of(run):
    return suite.kind_of(run["suite"])


def effort_of(run):
    return run.get("effort") or DEFAULT_EFFORT


def headline(runs, effort=DEFAULT_EFFORT):
    """For one effort, the newest complete full run represents a model; a quick run stands in, marked provisional, until one exists."""
    best = {}
    for run in runs:
        kind = kind_of(run)
        if kind not in KINDS or effort_of(run) != effort:
            continue
        current = best.get(run["model"])
        if current is None or KINDS.index(kind) < KINDS.index(kind_of(current)):
            best[run["model"]] = run
    return best


def task_entry(metrics, task):
    score = metrics.get(f"{task}.score")
    if not score:
        return None
    parts = {key.split(".", 2)[2]: entry["value"] for key, entry in metrics.items()
             if key.startswith(task) and any(key.startswith(task + prefix) for prefix in PART_PREFIXES)}
    return {**score, **{field: (metrics.get(f"{task}.{field}") or {}).get("value")
                        for field in ("tokens", "latency", "truncated", "unreachable", "malformed")},
            "parts": parts}


def warnings_for(tasks, capacity, labels):
    """Server settings that cap scores, said out loud so a low long-context score isn't read as the model's own."""
    out_of_reach = {task: entry["unreachable"] for task, entry in tasks.items() if entry.get("unreachable")}
    if not out_of_reach:
        return []
    limit = capacity.get("context")
    reach = f"{limit // 1024}k tokens per request" if limit else "the server's context window"
    return [f"Capped at {reach}: " + ", ".join(f"{labels.get(task, task)} {share:.0f}% out of reach"
                                              for task, share in out_of_reach.items())]


def linked_quality(db, run, definition):
    """A phone run measures speed on the device; its quality comes from a named desktop run of the same weights, so the
    two numbers are never taken for one measurement."""
    named = (run.get("flags") or {}).get("quality_from")
    if isinstance(named, dict):
        twin = named.get("twin")
        source = store.last_complete(db, twin) if twin else None
    else:
        source = store.get_run(db, named) if named else None
    if not source or suite.kind_of(source["suite"]) not in suite.QUALITY_SUITES:
        return None
    theirs = (source.get("server") or {}).get("weights")
    ours = (run.get("server") or {}).get("weights")
    if ours and theirs and ours != theirs:
        return None
    metrics = store.metrics_of(db, source["id"])
    tasks = {task: entry for task in definition["index_tasks"] if (entry := task_entry(metrics, task))}
    if not tasks:
        return None
    return {"run": source["id"], "model": source["model"], "suite": source["suite"],
            "host": stack.of(source)["hostLabel"],
            "verified": bool(ours and theirs and ours == theirs),
            "agreement": doctor.agreement((run.get("server") or {}).get("probe"),
                                          (source.get("server") or {}).get("probe")),
            "index": metrics.get("index.quality"), "tasks": tasks}


def repeatability(db, run, history):
    """How far apart repeats of the same configuration landed. A benchmark that has only measured a thing once has
    not measured its noise, and a phone is where that matters most."""
    same = [entry for entry in history
            if entry["status"] == "complete" and entry.get("fingerprint") == run.get("fingerprint")]
    values = [value for entry in same
              if (value := (store.metrics_of(db, entry["id"]).get("speed.decode_steady") or {}).get("value"))]
    if len(values) < 2:
        return {"runs": len(values) or 1, "spread": None}
    return {"runs": len(values), "spread": 100 * (max(values) - min(values)) / statistics.mean(values)}


def model_entry(db, run, history, definition):
    metrics = store.metrics_of(db, run["id"])
    profile = run.get("profile") or {}
    flags = run.get("flags") or {}
    lmx_scores = {}
    submissions = []
    for candidate in history:
        candidate_metrics = metrics if candidate["id"] == run["id"] else store.metrics_of(db, candidate["id"])
        for dataset in ("gsm8k", "hellaswag"):
            if dataset not in lmx_scores and f"lmx.{dataset}" in candidate_metrics:
                lmx_scores[dataset] = candidate_metrics[f"lmx.{dataset}"]
        for entry in store.submissions_of(db, candidate["id"]):
            if entry["kind"].startswith("speed."):
                detail = json.loads(entry["detail"]) if entry.get("detail") else {}
                submissions.append({"kind": entry["kind"], "id": entry["remote_id"], "value": entry["value"],
                                    "run": candidate["id"], "verified": detail.get("verified")})
    tasks = {task: entry for task in definition["index_tasks"] if (entry := task_entry(metrics, task))}
    linked = linked_quality(db, run, definition) if not tasks else None
    capacity = (run.get("server") or {}).get("capacity") or {}
    return {
        "id": run["model"],
        "name": run.get("name") or run["model"],
        "engine": profile.get("engine"),
        "quantization": profile.get("quantization"),
        "spec": (profile.get("spec") or {}).get("method"),
        "context": profile.get("context"),
        "fingerprint": run.get("fingerprint"),
        "stack": stack.of(run),
        "run": {
            "id": run["id"], "suite": run["suite"], "kind": kind_of(run), "finished": run.get("finished"),
            "effort": effort_of(run), "harness": run.get("harness"), "contended": flags.get("contended") or [],
            "failedItems": flags.get("failed_items") or 0, "notes": flags.get("notes"),
            "reused": flags.get("reused"), "stackChange": flags.get("stack_change") or [],
        },
        "index": metrics.get("index.quality") or (linked or {}).get("index"),
        "tasks": tasks or (linked or {}).get("tasks") or {},
        "qualityFrom": {key: value for key, value in (linked or {}).items()
                        if key in ("run", "model", "suite", "host", "verified", "agreement")} or None,
        "deviceClass": (run.get("hardware") or {}).get("class") or "gpu",
        "capacity": capacity,
        "warnings": warnings_for(tasks, capacity, definition["labels"]),
        "energy": {"perCorrect": metrics.get("energy.per_correct"), "quality": metrics.get("energy.quality")},
        "speed": {key.removeprefix("speed."): entry for key, entry in metrics.items() if key.startswith("speed.")},
        "thermal": {key.removeprefix("thermal."): entry for key, entry in metrics.items() if key.startswith("thermal.")},
        "battery": {key.removeprefix("battery."): entry for key, entry in metrics.items() if key.startswith("battery.")},
        "verdict": scores.verdict(metrics),
        "repeats": repeatability(db, run, history),
        "lmx": lmx_scores,
        "submissions": submissions,
        "server": run.get("server") or {},
        "history": [
            {"id": entry["id"], "suite": entry["suite"], "effort": effort_of(entry), "finished": entry.get("finished"),
             "index": (store.metrics_of(db, entry["id"]).get("index.quality") or {}).get("value"),
             "decode": (store.metrics_of(db, entry["id"]).get("speed.decode") or {}).get("value")}
            for entry in history
        ],
    }


def history_entry(db, run):
    """One finished run as the history keeps it: small enough to hold hundreds, and everything a trend or a feed needs."""
    metrics = store.metrics_of(db, run["id"])
    index = metrics.get("index.quality") or {}
    where = stack.of(run)

    def value(key):
        return (metrics.get(key) or {}).get("value")

    return {"run": run["id"], "model": run["model"], "name": run.get("name") or run["model"], "effort": effort_of(run),
            "suite": run["suite"], "version": suite.version_of(run["suite"]), "kind": kind_of(run),
            "finished": run.get("finished"), "index": index.get("value"), "lo": index.get("lo"), "hi": index.get("hi"),
            "decode": value("speed.decode"), "peak": value("speed.peak"), "energyPerCorrect": value("energy.per_correct"),
            "gpu": where["gpu"], "driver": where["driver"], "build": where["build"]}


def progress_of(run, definition):
    """Where a run in progress is: the quality tasks it will run, which are scored, which one it is answering and how far
    along that one is, read off the progress lines the worker keeps."""
    flags = run.get("flags") or {}
    plan = [task for task in ("speed", *suite.QUALITY_TASKS) if task in (flags.get("tasks") or ["speed", *suite.QUALITY_TASKS])]
    current = None
    try:
        lines = (paths.RUNS / run["id"] / "events.jsonl").read_text().splitlines()
    except OSError:
        lines = []
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "done" in event and event.get("phase") in plan:
            current = {"task": event["phase"], "done": event["done"], "total": event.get("total")}
            break
    return {"plan": plan, "current": current, "parked": flags.get("parked"), "yielded": flags.get("yielded", 0)}


def live_entry(db, run, definition):
    """A run still being measured, as the same entry a finished one gets plus how far it has got. Tasks that finished are
    scored; the index waits for the last one, so a reader sees what is known and what is still to come."""
    entry = model_entry(db, run, [run], definition)
    entry["index"] = None
    entry["progress"] = progress_of(run, definition)
    entry["run"]["started"] = run.get("started")
    entry["run"]["finished"] = None
    entry["history"] = []
    return entry


def live_runs(db, classes=None):
    found = [run for run in store.list_runs(db) if run["status"] in LIVE_STATUSES and kind_of(run) in ("full", "quick")
             and suite.version_of(run["suite"]) == suite.VERSION and (not classes or units.device_class(run) in classes)]
    definition = suite.DEFINITIONS[suite.VERSION]
    return [live_entry(db, run, definition) for run in sorted(found, key=lambda run: run.get("started") or run["created"])]


def hosts(models):
    """Every card and driver a ranking's speed numbers come from, the one with most models first."""
    counts = {}
    for model in models:
        entry = model["stack"]
        found = counts.setdefault(entry["host"], {"key": entry["host"], "label": entry["hostLabel"], "models": 0})
        found["models"] += 1
    return sorted(counts.values(), key=lambda entry: -entry["models"])


def effort_key(name):
    return (EFFORT_ORDER.index(name) if name in EFFORT_ORDER else len(EFFORT_ORDER), name)


def suite_view(db, runs, version):
    """One suite version's rankings; versions measure different tasks, so their indexes are never ranked together."""
    definition = suite.DEFINITIONS[version]
    rankings = {}
    for effort in sorted({effort_of(run) for run in runs}, key=effort_key):
        chosen = headline(runs, effort)
        if chosen:
            rankings[effort] = [model_entry(db, run, [entry for entry in runs if entry["model"] == model_id], definition)
                                for model_id, run in chosen.items()]
    return {
        "indexTasks": list(definition["index_tasks"]),
        "taskLabels": definition["labels"],
        "taskShort": definition["short"],
        "taskNotes": definition["notes"],
        "groups": {name: list(tasks) for name, tasks in definition["groups"].items()},
        "efforts": list(rankings),
        "rankings": rankings,
        "health": {effort: scores.task_health(models, definition["index_tasks"]) for effort, models in rankings.items()},
        "hosts": {effort: hosts(models) for effort, models in rankings.items()},
    }


def collect(db, classes=None):
    """Every ranking in the database, or only those from the named hardware classes. The published page is the card's
    alone; phones and other machines stay in the database and in `blackwall ls --device`."""
    runs = [run for run in store.list_runs(db, status="complete") if not classes or units.device_class(run) in classes]
    ranked = [run for run in runs if kind_of(run) in KINDS and suite.version_of(run["suite"]) in suite.DEFINITIONS]
    versions = sorted({suite.version_of(run["suite"]) for run in ranked} | {suite.VERSION}, key=int, reverse=True)
    suites = {version: suite_view(db, [run for run in ranked if suite.version_of(run["suite"]) == version], version)
              for version in versions}
    latest = ranked[0] if ranked else None
    finished = [run for run in ranked if kind_of(run) in HISTORY_KINDS and run.get("finished")]
    return {
        "schema": SCHEMA,
        "generator": {"name": "blackwall", "version": __version__},
        "generated": time.time(),
        "suite": suite.label("full"),
        "current": suite.VERSION,
        "hardware": (latest or {}).get("hardware") or {},
        "suites": suites,
        **{key: suites[suite.VERSION][key] for key in ("indexTasks", "taskLabels", "efforts", "rankings")},
        "history": timeline.annotate([history_entry(db, run) for run in finished]),
        "live": live_runs(db, classes),
    }


def publishable(data, indent=None):
    """The data as JSON anyone can be given: nothing in it names the home directory of the machine that measured."""
    text = json.dumps(data, indent=indent)
    home = str(Path.home())
    return text.replace(home, "~") if len(home) > 1 else text


def plain_table(data):
    """The ranking as a plain table inside <noscript>, so the board reads with scripts off and to anything that does not
    run them: the effort with the most timed models, best quality first."""
    view = (data.get("suites") or {}).get(data.get("current")) or {}
    rankings = view.get("rankings") or {}
    if not rankings:
        return ""
    timed = lambda effort: sum(1 for model in rankings[effort] if "decode" in (model.get("speed") or {}))
    effort = max(rankings, key=lambda name: (timed(name), len(rankings[name])))
    rows = []
    for model in sorted(rankings[effort], key=lambda entry: -((entry.get("index") or {}).get("value") or -1)):
        index = (model.get("index") or {}).get("value")
        decode = ((model.get("speed") or {}).get("decode") or {}).get("value")
        rows.append(f"<tr><td>{html.escape(model['name'].split(' · ')[0])}</td>"
                    f"<td>{'' if index is None else f'{index:.1f}'}</td><td>{'' if decode is None else f'{decode:.0f}'}</td></tr>")
    return (f"<noscript><p>The interactive board needs JavaScript. Ranked by quality index at {html.escape(effort)} effort:</p>"
            "<table><thead><tr><th>Model</th><th>Quality index</th><th>Decode, tok/s</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></noscript>")


def page(data, template=None):
    """The whole leaderboard as one self-contained file: the template with the run data baked in."""
    text = (template or TEMPLATE).read_text().replace("/*__DATA__*/null", publishable(data))
    return text.replace("<!--__NOSCRIPT__-->", plain_table(data))


def build():
    db = store.connect()
    paths.BOARD.parent.mkdir(parents=True, exist_ok=True)
    data = collect(db)
    paths.BOARD.write_text(page(data))
    (paths.BOARD.parent / "card.html").write_text(page(data, CARD))
    return paths.BOARD


def rebuild():
    """Rebuilds the local page in a fresh interpreter. A worker holds the Blackwall it started with for as long as a run
    takes, and the template it reads from disk can be newer than that code: a placeholder renamed between the two once
    left a stray marker on the page. Code and template only match when one process reads both at the same moment."""
    completed = subprocess.run([sys.executable, "-m", "blackwall.cli", "board"], capture_output=True, text=True,
                               timeout=REBUILD_TIMEOUT_S, env={**os.environ, "BLACKWALL_HOME": str(paths.DATA)})
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip()[-300:] or f"exit status {completed.returncode}")
    return Path(completed.stdout.strip())


def addressed(html, site_url):
    """The page told where it lives. Link previews only follow absolute addresses, so the share card and the canonical
    link name the site; opened from a folder, the page keeps its relative ones."""
    image = '<meta property="og:image" content="card.png">'
    assert image in html
    return html.replace(image, f'<meta property="og:image" content="{site_url}card.png">\n'
                               f'<meta property="og:url" content="{site_url}">\n<link rel="canonical" href="{site_url}">')


def export(db, directory, site_url=None):
    """A folder anyone can serve: the page, plus the same numbers as JSON so other tools can read them. Given the
    address the folder will be served from, it adds an Atom feed of new results, which has to name that address."""
    site_url = site_url or notify.settings().get("site_url")
    site_url = feed.address(site_url) if site_url else None
    data = collect(db, PUBLISHED_CLASSES)
    data["published"] = {"json": "board.json", "feed": "feed.xml" if site_url else None}
    directory.mkdir(parents=True, exist_ok=True)
    written = {"index.html": page(data), "card.html": page(data, CARD), "board.json": publishable(data, indent=1) + "\n"}
    if site_url:
        written["index.html"] = addressed(written["index.html"], site_url)
        written["feed.xml"] = feed.atom(data["history"], site_url)
    for name, text in written.items():
        (directory / name).write_text(text)
    return [directory / name for name in written]
