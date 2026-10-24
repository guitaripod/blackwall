import statistics
import subprocess
import threading
import time
from collections import defaultdict
from pathlib import Path

SERVER_PROCESS_NAMES = ("sglang", "llama-server", "llama-swap", "vllm")
DISPLAY_PROCESS_NAMES = ("kwin_wayland", "kwin_x11", "Xwayland", "Xorg", "gnome-shell", "mutter", "sway", "Hyprland",
                         "niri", "weston")
INTERPRETERS = ("python", "node", "bun", "deno", "java", "ruby", "perl", "bash", "sh")
BUSY_SM_PERCENT = 25
BUSY_SM_SEVERE = 60
MIN_SHARE_SM = 5
RANK = {"mild": 1, "severe": 2}
STRICT_PHASES = ("speed", "submit")
HEAVY_MIB = 4096
FREE_MIB_FLOOR = 4096


class Sampler:
    """Samples board power, VRAM and utilisation on an interval so each measurement can report its own window."""

    def __init__(self, interval_ms=250):
        self.samples = []
        self.process = subprocess.Popen(
            ["nvidia-smi", "--query-gpu=power.draw,memory.used,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits", "-lms", str(interval_ms)],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        for line in self.process.stdout or []:
            try:
                power, memory, utilization, temperature = (float(part) for part in line.split(","))
            except ValueError:
                continue
            self.samples.append((time.time(), power, memory, utilization, temperature))

    def window(self, start, end):
        inside = [sample for sample in self.samples if start <= sample[0] <= end]
        if not inside:
            return {}
        busy = [sample for sample in inside if sample[3] >= 30] or inside
        return {"power_w": round(statistics.mean(sample[1] for sample in busy), 1),
                "vram_mib": max(sample[2] for sample in inside),
                "temp_c": round(max(sample[4] for sample in inside), 1)}

    def timeline(self):
        """A card reports power, not a thermal state; the phone's timeline has no counterpart here."""
        return []

    def energy_wh(self, start, end):
        """Board energy between two moments from the power samples, idle draw included; None without enough samples."""
        points = [(sample[0], sample[1]) for sample in self.samples if start <= sample[0] <= end]
        if len(points) < 2:
            return None
        joules = sum((later[0] - earlier[0]) * (earlier[1] + later[1]) / 2 for earlier, later in zip(points, points[1:]))
        return joules / 3600

    def close(self):
        self.process.kill()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


def compute_apps():
    completed = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"],
        capture_output=True, text=True,
    )
    apps = []
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) == 3 and parts[2].isdigit():
            apps.append({"pid": int(parts[0]), "name": parts[1], "mib": int(parts[2])})
    return apps


def basename(path):
    """The last part of a Linux path or a Windows one (games under Proton report S:\\...\\Game.exe)."""
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def program_name(args):
    """What a process is called: its executable, and for an interpreter the script it runs (ComfyUI is python main.py).
    Read from the argument list, since in the joined command line the last slash can sit in an argument (Xwayland's
    -auth path) and a space can sit in the executable's own path (a game under Proton). A process that rewrote its
    title into one string gets it cut at the first option instead."""
    if not args:
        return "?"
    if len(args) == 1:
        args = [args[0].split(" -")[0].strip()]
    name = basename(args[0])
    if name.rstrip("0123456789.") in INTERPRETERS:
        script = next((arg for arg in args[1:] if not arg.startswith("-")), None)
        if script and "-c" not in args[1:args.index(script)]:
            return f"{name} {basename(script)}"
    return name or "?"


def number(text):
    try:
        return float(text)
    except ValueError:
        return 0.0


def pmon_rows(text):
    """nvidia-smi pmon's table as dicts keyed by its own header, so older drivers with fewer columns still parse."""
    columns, rows = None, []
    for line in text.splitlines():
        if line.startswith("#"):
            columns = columns or line.lstrip("#").split()
            continue
        parts = line.split()
        if columns and len(parts) >= len(columns):
            head = len(columns) - 1
            rows.append({**dict(zip(columns[:head], parts[:head])), columns[-1]: " ".join(parts[head:])})
    return rows


def argv(pid):
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode(errors="replace") for part in raw.split(b"\0") if part]


def cmdline(pid):
    return " ".join(argv(pid)).strip()


def parent_of(pid):
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        return None


def is_server(pid):
    """A model server or anything llama-swap started: the benchmark's own GPU work, never contention."""
    for _ in range(64):
        if not pid or pid <= 1:
            return False
        if any(name in cmdline(pid) for name in SERVER_PROCESS_NAMES):
            return True
        pid = parent_of(pid)
    return False


def processes(samples=3):
    """Every GPU process with its SM use averaged over one-second samples and the VRAM it holds."""
    completed = subprocess.run(["nvidia-smi", "pmon", "-c", str(samples), "-s", "um"],
                               capture_output=True, text=True, timeout=30 + 2 * samples)
    sm, mib, names = defaultdict(list), defaultdict(float), {}
    for row in pmon_rows(completed.stdout):
        if not row.get("pid", "").isdigit():
            continue
        pid = int(row["pid"])
        sm[pid].append(number(row.get("sm", "-")))
        mib[pid] = max(mib[pid], number(row.get("fb", "-")))
        names[pid] = row.get("command", "")
    if not names:
        for app in compute_apps():
            sm[app["pid"]], mib[app["pid"]], names[app["pid"]] = [0.0], float(app["mib"]), app["name"]
    return [{"pid": pid, "name": program_name(argv(pid) or [names[pid]]), "sm": statistics.mean(sm[pid]),
             "mib": int(mib[pid]), "server": is_server(pid)} for pid in names]


def free_mib():
    """VRAM the card can still hand out; below the floor, a co-tenant can fail the model's next request."""
    completed = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=15)
    try:
        total, used = (float(part) for part in completed.stdout.strip().split(","))
    except ValueError:
        return None
    return total - used


def severity(process):
    """How much another program can move a speed number. Severe means it could take the card or squeeze it dry: a game,
    ComfyUI with models loaded. Mild is a share of the SMs that a speed run must not measure through but a quality run
    can live with, because answers do not depend on how fast they arrive."""
    if process["mib"] >= HEAVY_MIB or process["sm"] >= BUSY_SM_SEVERE:
        return "severe"
    if process["sm"] >= BUSY_SM_PERCENT:
        return "mild"
    return None


def strict_for(phase):
    """Whether a phase of a run is spoiled by anything sharing the card: a speed number and a submission's timing are,
    the answers a quality pass collects are not."""
    return phase in STRICT_PHASES


def blocking(candidates, strict):
    """The programs that should stop a run, given every program sharing the card besides the model servers and the
    display. Each is graded alone first; then the whole lot is graded as one share of the SMs, because four tabs at
    20% starve a server as surely as one program at 80%, and no single one of them crosses a line."""
    graded = [{**process, "severity": severity(process)} for process in candidates]
    found = [process for process in graded if process["severity"] == "severe" or (process["severity"] and strict)]
    shared = severity({"sm": sum(process["sm"] for process in candidates), "mib": 0})
    worst = max((RANK[process["severity"]] for process in found), default=0)
    if shared and RANK[shared] > worst and (shared == "severe" or strict):
        found = [{**process, "severity": shared} for process in candidates if process["sm"] >= MIN_SHARE_SM]
    return found


def starved(room):
    """A card with too little VRAM left, as the single thing keeping a run from carrying on."""
    if room is None or room >= FREE_MIB_FLOOR:
        return []
    return [{"name": f"a card with {room / 1024:.1f} GB free", "sm": 0.0, "mib": 0, "pid": 0, "server": False,
             "severity": "severe"}]


def contention(samples=3, strict=True):
    """Other GPU work big enough to matter. Strict is for speed: anything sharing the card spoils the number. Relaxed
    is for quality, where only work that could starve the server (most of the SMs, or most of the free VRAM) stops a
    run, so a browser tab no longer parks a three-hour quality pass for ten minutes a time."""
    candidates = [process for process in processes(samples)
                  if not process["server"] and process["name"] not in DISPLAY_PROCESS_NAMES]
    return blocking(candidates, strict) or starved(free_mib())


def describe_contention(found):
    return ", ".join(f"{process['name']} ({process['sm']:.0f}% GPU, {process['mib'] / 1024:.1f} GB)"
                     if process["sm"] or process["mib"] else process["name"] for process in found)


def health():
    """The card as the driver sees it right now; None when nvidia-smi cannot reach it at all, which is what a GPU that
    has fallen off the bus looks like from here."""
    completed = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu,power.draw", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True)
    parts = [part.strip() for part in completed.stdout.split(",")]
    if completed.returncode != 0 or len(parts) != 2:
        return None
    try:
        return {"temp_c": float(parts[0]), "power_w": float(parts[1])}
    except ValueError:
        return None


def last_fault(minutes=10):
    """The newest Xid the kernel logged, which names what the driver hit when the card stopped answering."""
    completed = subprocess.run(["journalctl", "-k", "--since", f"-{minutes}min", "-o", "cat", "--no-pager"],
                               capture_output=True, text=True)
    faults = [line for line in completed.stdout.splitlines() if "Xid" in line]
    return faults[-1].split("NVRM: ")[-1] if faults else None


def describe():
    completed = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
        capture_output=True, text=True,
    )
    name, driver, memory = [part.strip() for part in completed.stdout.splitlines()[0].split(",")]
    return {"gpu": name, "driver": driver, "vram_mib": int(memory)}


def top_memory_users(count=5):
    """The programs holding the most resident memory right now, processes of one name summed (a compile is thirty `cc1plus`
    and a browser is forty), as (name, GB) pairs largest first. What a run records when RAM runs short, so the next
    stop names its cause."""
    totals = {}
    for status in Path("/proc").glob("[0-9]*/status"):
        try:
            fields = dict(line.split(":", 1) for line in status.read_text().splitlines() if ":" in line)
            kib = int(fields.get("VmRSS", "0 kB").split()[0])
        except (OSError, ValueError):
            continue
        name = fields.get("Name", "?").strip()
        totals[name] = totals.get(name, 0) + kib
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:count]
    return [(name, round(kib / 1048576, 1)) for name, kib in ranked]


def mem_available_gb():
    with open("/proc/meminfo") as handle:
        for line in handle:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1048576
    return 0.0
