import os
from pathlib import Path

HOME = Path.home()
DATA = Path(os.environ.get("BLACKWALL_HOME", HOME / ".local/share/blackwall"))
CACHE = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "blackwall"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "blackwall"
DB = DATA / "bench.db"
RUNS = DATA / "runs"
BOARD = DATA / "leaderboard.html"
PROFILES = CONFIG / "models.toml"
SETTINGS = CONFIG / "config.toml"
HARDWARE = CONFIG / "hardware.json"
LLAMA_SWAP_CONFIG = Path(os.environ.get("BLACKWALL_SWAP_CONFIG", HOME / ".config/llama-swap/config.yaml"))
OMP_MODELS = Path(os.environ.get("BLACKWALL_OMP_MODELS", HOME / ".omp/agent/models.yml"))
SWAP_URL = os.environ.get("BLACKWALL_SWAP_URL", "http://127.0.0.1:8081").rstrip("/")
PACKAGE = Path(__file__).resolve().parent
ASSETS = PACKAGE / "assets"
