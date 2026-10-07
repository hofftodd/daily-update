"""Where am I? The freshest of the Mac's own fix and the last phone report, reverse-geocoded.

The phone posts to the server's /api/location endpoint, which writes data/location/phone.json.
"""

import shutil
import subprocess
from datetime import datetime, timedelta, timezone

from core.common import DATA, http_get, log, read_json, write_atomic

PHONE_PATH = DATA / "location" / "phone.json"
GEOCODE_CACHE = DATA / "cache" / "geocode.json"


def mac_location():
    """One fix from macOS Location Services via CoreLocationCLI (brew install corelocationcli).
    The first run triggers a permission prompt for CoreLocationCLI; launchd runs can't answer it."""
    exe = shutil.which("CoreLocationCLI") or "/opt/homebrew/bin/CoreLocationCLI"
    if not shutil.which(exe):
        return None
    try:
        out = subprocess.run(
            [exe, "--format", "%latitude %longitude %h_accuracy"],
            capture_output=True, text=True, timeout=20,
        ).stdout.split()
        lat, lon, acc = (float(x) for x in out[:3])
    except Exception as e:
        log(f"Mac location unavailable: {e}")
        return None
    return {"lat": lat, "lon": lon, "accuracy_m": acc, "time": datetime.now(timezone.utc).isoformat(), "source": "mac"}


def phone_location():
    loc = read_json(PHONE_PATH)
    return {**loc, "source": "phone"} if loc and "lat" in loc else None


def reverse_geocode(lat, lon):
    """City / region / country from OpenStreetMap Nominatim, cached on a ~1 km grid (their policy is 1 req/s)."""
    key = f"{lat:.2f},{lon:.2f}"
    cache = read_json(GEOCODE_CACHE, {})
    if key in cache:
        return cache[key]
    try:
        r = http_get("https://nominatim.openstreetmap.org/reverse", {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 12})
        a = r.get("address", {})
        place = {
            "city": a.get("city") or a.get("town") or a.get("village") or a.get("hamlet") or a.get("county"),
            "region": a.get("state"),
            "country": a.get("country"),
            "country_code": (a.get("country_code") or "").upper(),
            "display": r.get("display_name"),
        }
    except Exception as e:
        log(f"reverse geocode failed: {e}")
        return {"city": None, "region": None, "country": None, "country_code": "", "display": f"{lat:.3f}, {lon:.3f}"}
    cache[key] = place
    write_atomic(GEOCODE_CACHE, cache)
    return place


def geocode(query):
    """Place name -> {"lat", "lon", "place"} from Nominatim, or None. Cached by query alongside reverse lookups."""
    key = f"q:{query.strip().lower()}"
    cache = read_json(GEOCODE_CACHE, {})
    if key in cache:
        return cache[key]
    try:
        hits = http_get("https://nominatim.openstreetmap.org/search", {"q": query, "format": "jsonv2", "limit": 1})
    except Exception as e:
        log(f"geocode failed for {query!r}: {e}")
        return None
    if not hits:
        found = None
    else:
        lat, lon = float(hits[0]["lat"]), float(hits[0]["lon"])
        found = {"lat": lat, "lon": lon, "place": reverse_geocode(lat, lon)}
    cache = read_json(GEOCODE_CACHE, {})  # reverse_geocode may have written it
    cache[key] = found
    write_atomic(GEOCODE_CACHE, cache)
    return found


def _age(loc):
    return datetime.now(timezone.utc) - datetime.fromisoformat(loc["time"])


def current_location(cfg):
    """Prefer whichever fresh fix is newer; then the last phone fix if it's from the last few days (away from home,
    a stale fix is still closer than home; the page shows its age); then the home location from config."""
    cfg = cfg or {}
    candidates = []
    mac = mac_location()
    if mac and _age(mac) <= timedelta(minutes=cfg.get("mac_max_age_min", 30)):
        candidates.append(mac)
    phone = phone_location()
    if phone and _age(phone) <= timedelta(minutes=cfg.get("phone_max_age_min", 240)):
        candidates.append(phone)
    if candidates:
        loc = max(candidates, key=lambda l: l["time"])
    elif phone and _age(phone) <= timedelta(hours=cfg.get("last_known_max_hours", 72)):
        loc = phone
    else:
        home = cfg["home"]
        loc = {"lat": home["lat"], "lon": home["lon"], "time": datetime.now(timezone.utc).isoformat(), "source": "home (no fresh fix)"}
    loc["place"] = reverse_geocode(loc["lat"], loc["lon"])
    return loc


def place_label(loc):
    p = loc.get("place") or {}
    parts = [p.get("city"), p.get("region") if p.get("country_code") == "US" else p.get("country")]
    return ", ".join(x for x in parts if x) or p.get("display") or f"{loc['lat']:.3f}, {loc['lon']:.3f}"
