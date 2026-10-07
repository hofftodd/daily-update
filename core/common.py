"""Shared paths and small helpers."""

import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
CONFIG_PATH = ROOT / "config.json"
USER_AGENT = "daily-update (personal use)"

_log_lock = threading.Lock()


def log(msg):
    with _log_lock:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", file=sys.stderr, flush=True)


def load_env():
    """Load KEY=VALUE lines from .env (launchd doesn't inherit the shell environment)."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_config_lock = threading.Lock()


def load_config():
    """Read fresh on every use, so edits to config.json (by hand or from the settings sheet) apply right away."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json is missing: copy config.example.json to config.json (install.sh does this)")
    return json.loads(CONFIG_PATH.read_text())


def update_config(mutate):
    """Read-modify-write config.json under a lock. `mutate(config)` edits it in place."""
    with _config_lock:
        config = load_config()
        mutate(config)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(config, indent=2) + "\n")
        tmp.replace(CONFIG_PATH)
        return config


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_atomic(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(payload, indent=1))
    tmp.replace(path)


def http_get(url, params=None, as_json=True, timeout=30, headers=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"
    accept = "application/geo+json, application/json" if as_json else "*/*"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept, **(headers or {})})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
            return json.loads(body) if as_json else body
        except urllib.error.HTTPError as e:
            # Back off on rate limits, intermittent blocks (NRCS returns sporadic 403s) and server errors;
            # anything else (404 etc.) won't improve.
            if attempt == 3 or not (e.code in (403, 429) or e.code >= 500):
                raise
            retry_after = e.headers.get("Retry-After")
            time.sleep(min(30, int(retry_after)) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1))


def km_between(a, b):
    """Great-circle distance between two {lat, lon} dicts."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def slot_passed(stamp, hours):
    """True once a scheduled local hour has passed since `stamp` (catches up after sleep).
    No hours means manual only."""
    if not hours:
        return False
    if not stamp:
        return True
    now = datetime.now().astimezone()
    slots = [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in sorted(hours)]
    past = [t for t in slots if t <= now] or [slots[-1] - timedelta(days=1)]
    return datetime.fromisoformat(stamp) < max(past)
