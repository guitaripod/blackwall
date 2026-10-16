import re
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import quoteattr as xml_quoteattr

from . import __version__, timeline

TITLE = "Blackwall"
SUBTITLE = "New results on one NVIDIA RTX PRO 6000 Blackwell, in the order they finished."
LIMIT = 30


def clean(text):
    """XML cannot carry control characters at all, so a model name that has one loses it instead of breaking the feed."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(text))


def escape(text):
    return xml_escape(clean(text))


def quoteattr(text):
    return xml_quoteattr(clean(text))


def address(site_url):
    """The site's address as the feed and the page use it: a full http or https address ending in a slash, without a
    query or fragment that would turn every link built from it into nonsense."""
    parts = urlsplit(site_url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"{site_url!r} is not a full address; give it like https://you.example/bench/")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}/"


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def short_name(entry):
    return (entry.get("name") or entry["model"]).split(" · ")[0]


def title_of(entry):
    """What a feed reader lists: the model, its quality index, and what the result meant for the board."""
    name = short_name(entry)
    if entry.get("index") is None:
        return f"{name}: measured without a quality index"
    note = " (new best)" if entry["record"] else " (debut)" if entry["debut"] else ""
    return f"{name}: {entry['index']:.1f} quality{note}"


def sentences_of(entry):
    """The result in words: effort and suite, the numbers a reader chooses a model by, then what changed."""
    parts = [f"{entry['effort'].capitalize()} effort, suite {entry['suite']}."]
    if entry.get("index") is not None:
        spread = f" (95% interval {entry['lo']:.1f} to {entry['hi']:.1f})" if entry.get("lo") is not None else ""
        parts.append(f"Quality index {entry['index']:.1f}{spread}.")
    speed = [f"{entry['decode']:.0f} tok/s decoding one request" if entry.get("decode") else None,
             f"{entry['peak']:.0f} tok/s at peak" if entry.get("peak") else None,
             f"{entry['energyPerCorrect']:.2f} Wh per correct answer" if entry.get("energyPerCorrect") else None]
    if any(speed):
        said = ", ".join(item for item in speed if item)
        parts.append(said[0].upper() + said[1:] + ".")
    if entry["record"]:
        parts.append("The best quality index on this card at this effort so far.")
    elif entry["debut"]:
        parts.append("First time this model is on the board.")
    if entry.get("delta"):
        parts.append(f"{entry['delta']:+.1f} against its previous run.")
    where = [entry.get("gpu"), f"driver {entry['driver']}" if entry.get("driver") else None, entry.get("build")]
    if any(where):
        parts.append("Measured on " + ", ".join(item for item in where if item) + ".")
    if entry["kind"] == "quick":
        parts.append("A quick run, ranked as provisional.")
    return " ".join(parts)


def entry_xml(entry, site_url, authority):
    day = datetime.fromtimestamp(entry["finished"], timezone.utc).strftime("%Y-%m-%d")
    link = f"{site_url}#{quote(entry['model'], safe='')}~{quote(entry['effort'], safe='')}"
    return (f"  <entry>\n    <id>tag:{authority},{day}:run/{escape(entry['run'])}</id>\n"
            f"    <title>{escape(title_of(entry))}</title>\n    <updated>{stamp(entry['finished'])}</updated>\n"
            f"    <link rel=\"alternate\" href={quoteattr(link)}/>\n"
            f"    <summary>{escape(sentences_of(entry))}</summary>\n  </entry>\n")


def atom(history, site_url, limit=LIMIT):
    """An Atom feed of the newest finished runs. Entry ids are tag URIs built from the run, so a reader never shows the
    same result twice however often the site is rebuilt; the feed is addressed from site_url, which is why it takes one."""
    site_url = address(site_url)
    authority = urlsplit(site_url).hostname or "localhost"
    recent = [entry for entry in timeline.newest_first(history) if entry.get("finished")][:limit]
    updated = stamp(recent[0]["finished"]) if recent else stamp(datetime.now(timezone.utc).timestamp())
    head = ("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<feed xmlns=\"http://www.w3.org/2005/Atom\">\n"
            f"  <id>{escape(site_url)}</id>\n  <title>{TITLE}</title>\n  <subtitle>{escape(SUBTITLE)}</subtitle>\n"
            f"  <updated>{updated}</updated>\n  <author><name>{TITLE}</name></author>\n"
            f"  <generator version=\"{__version__}\">blackwall</generator>\n"
            f"  <link rel=\"self\" type=\"application/atom+xml\" href={quoteattr(site_url + 'feed.xml')}/>\n"
            f"  <link rel=\"alternate\" type=\"text/html\" href={quoteattr(site_url)}/>\n")
    return head + "".join(entry_xml(entry, site_url, authority) for entry in recent) + "</feed>\n"
