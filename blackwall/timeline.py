import math


def comparable(entry):
    """The boundary a quality index is compared inside: one suite version at one effort level, the same boundary the
    board ranks within. A different suite measures different tasks, and a different effort is a different question."""
    return entry["version"], entry["effort"]


def annotate(entries):
    """The finished runs in the order they happened, each marked with what it changed: a model's first appearance on the
    board, a new best quality index, and how far a repeat landed from the model's previous run. Without an index a run
    can debut but never set a record or move. A quick run is provisional, as it is on the board: it can debut, but only a
    full run sets a record, and a repeat is compared with the previous run of the same kind."""
    best = {}
    previous = {}
    seen = set()
    ordered = sorted(entries, key=lambda entry: (entry.get("finished") or 0, entry["run"]))
    annotated = []
    for entry in ordered:
        group = comparable(entry)
        key = (entry["model"], *group)
        mark = {"debut": key not in seen, "record": False, "delta": None, "previous": None}
        seen.add(key)
        value = entry.get("index")
        if value is not None:
            if entry.get("kind") != "quick" and value > best.get(group, -math.inf):
                mark["record"] = True
                best[group] = value
            key = (*key, entry.get("kind"))
            earlier = previous.get(key)
            if earlier is not None:
                mark["delta"] = round(value - earlier["index"], 1)
                mark["previous"] = earlier["run"]
            previous[key] = entry
        annotated.append({**entry, **mark})
    return annotated


def newest_first(history, limit=None):
    """The history as a reader follows it: the latest result first."""
    latest = sorted(history, key=lambda entry: (entry.get("finished") or 0, entry["run"]), reverse=True)
    return latest if limit is None else latest[:limit]
