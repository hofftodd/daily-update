"""Local: research on wherever you are right now, shaped by your interests.

Two research calls per run, both with web search and neither seeing email or calendar:
  - events: specific things happening in the next `horizon_days`, each with a date so the page can group by day;
  - good to know: news, openings, closures, conditions and local tips that aren't tied to a date.

Research runs at the summary slots, and also as soon as you've moved `trigger_km` from where it last ran.

A section with "place" ({label, lat, lon}) is pinned there instead of following you, and one with "trip" ({start,
end, purpose}) researches those dates. sections/_trips.py creates such tabs for travel it finds on the calendar.
"""

from datetime import date, datetime, timezone

from core.common import km_between
from sections._here import locate_here, location_summary, weather_line
from sections._research import FINDING, FINDINGS_SCHEMA, METHOD, interests_block, research
from sources import weather

TITLE = "Local"
ICON = "📍"
USES_INTERESTS = True  # the settings sheet shows the shared interests editor

DEFAULTS = {"trigger_km": 40, "horizon_days": 14, "max_events": 12, "max_info": 8, "max_searches": 10}

# Short highlights for the top of the page; a list of what couldn't be confirmed isn't worth the space there.
SUMMARY = "One or two sentences, under ~200 characters: the highlights for this person. Don't list gaps or caveats."
INFO_SCHEMA = {**FINDINGS_SCHEMA, "properties": {**FINDINGS_SCHEMA["properties"], "summary": {"type": "string", "description": SUMMARY}}}

EVENTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "events"],
    "properties": {
        "summary": {"type": "string", "description": SUMMARY},
        "events": {"type": "array", "items": {
            **FINDING,
            "required": FINDING["required"] + ["date", "interest"],
            "properties": {
                **FINDING["properties"],
                "category": {**FINDING["properties"]["category"], "description": "What kind of event it is: music, sports, food & drink, outdoors, culture, family, or event if none fit. Never venue."},
                "date": {"type": ["string", "null"], "description": "Start date as YYYY-MM-DD, from the source. Null only for multi-week runs with no single date."},
                "interest": {"type": ["string", "null"], "description": "Which of their interests this matches, copied exactly, or null."},
            },
        }},
    },
}

EVENTS = """You are a helpful personal assistant who understands this person's interests and what they like. Do \
research on {place} and figure out the current events and happenings there (and within about an hour's drive) \
between {start} and {end} that they would be interested in and actually want to go to. Search \
per interest: event calendars, venue schedules, team and league schedules, local news and tourism sites. Every event \
needs a confirmed date in that window, and a title that says what it is (the performer, teams or event name, not \
"live show at <venue>"): skip listings where you can't find that. Spread findings across their interests rather \
than ten of one kind.

""" + METHOD
INFO = """You are a helpful personal assistant who understands this person's interests and what they like. Do \
research on {place} and figure out what's happening there right now that they would be interested in: new or \
reopened places, closures, seasonal openings, current outdoor and trail conditions, local news \
that affects their plans, and the kind of tip a well-connected local would pass along. Leave out anything that \
happens on a specific date or date range (a show, festival, conference, game or race): those are covered separately. \
Also leave out anything generic or evergreen.

""" + METHOD


def _cfg(ctx):
    return {**DEFAULTS, **(ctx.cfg.get("research") or {})}


# ---------------------------------------------------------------- gather


def gather(ctx):
    pinned = ctx.cfg.get("place")
    if pinned:
        loc = {"lat": pinned["lat"], "lon": pinned["lon"], "source": "trip", "time": datetime.now(timezone.utc).isoformat()}
        label = pinned["label"]
    else:
        ctx.status("Finding your location…")
        loc, label = locate_here(ctx)
    ctx.scratch["location"] = loc
    wx = None
    try:
        wx = weather.fetch_quick(loc["lat"], loc["lon"], ctx.units)
    except Exception as e:
        ctx.error(f"Weather unavailable: {e}")
    return {"units": ctx.units, "location": location_summary(loc, label), "weather_line": weather_line(wx),
            "trip": ctx.cfg.get("trip")}


# ---------------------------------------------------------------- research


def summary_due(ctx):
    """Moving somewhere new (or the Explore button) brings research forward instead of waiting for the next slot."""
    loc = ctx.scratch.get("location")
    if not loc:
        return False
    if (ctx.dir / "force").exists():
        return True
    if ctx.cfg.get("place"):
        return False  # pinned: it doesn't move
    last = (ctx.prev.get("summary") or {}).get("location")
    return not last or km_between(loc, last) >= _cfg(ctx)["trigger_km"]


def summarize(ctx, data):
    rc = _cfg(ctx)
    loc, label = ctx.scratch["location"], data["location"]["label"]
    today = date.today()
    trip = ctx.cfg.get("trip")
    if trip:
        today = max(today, date.fromisoformat(trip["start"]))
        end = max(today, date.fromisoformat(trip["end"]))
    else:
        end = date.fromordinal(today.toordinal() + rc["horizon_days"])
    context = f"Location: {label} ({loc['lat']:.3f}, {loc['lon']:.3f})\nWeather there now: {data['weather_line']}\n{interests_block(ctx)}"
    if trip:
        context += (f"\n\nThey're traveling there from {trip['start']} to {trip['end']} for: {trip['purpose']}. "
                    "They're a visitor: favor what's useful during those dates.")

    ctx.status(f"Finding events around {label}…")
    events = research(
        ctx, "local_events", EVENTS.replace("{place}", label).replace("{start}", f"{today:%b %-d}").replace("{end}", f"{end:%b %-d}"),
        f"{context}\n\nFind events for them from {today:%A, %B %-d} through {end:%A, %B %-d}.",
        max_findings=rc["max_events"], max_searches=rc["max_searches"], schema=EVENTS_SCHEMA, key="events",
    )
    for e in events["events"]:
        e["date"] = (e["date"] or "")[:10] or None
    events["events"].sort(key=lambda e: e["date"] or "9999")

    ctx.status(f"Finding what's new around {label}…")
    info = None
    try:
        info = research(ctx, "local_info", INFO.replace("{place}", label), f"{context}\n\nWhat should they know {'for their trip' if trip else 'about right now'}?",
                        max_findings=rc["max_info"], max_searches=rc["max_searches"], schema=INFO_SCHEMA)
    except Exception as e:
        ctx.error(f"Good-to-know research failed: {e}")
        info = (ctx.prev.get("summary") or {}).get("info")

    (ctx.dir / "force").unlink(missing_ok=True)
    return {"place": label, "location": {"lat": loc["lat"], "lon": loc["lon"]},
            "researched_at": datetime.now(timezone.utc).isoformat(), "events": events, "info": info}


# ---------------------------------------------------------------- page


def present(ctx, payload):
    """Events that have already happened drop off between runs."""
    ev = (payload.get("summary") or {}).get("events")
    if ev:
        today = date.today().isoformat()
        ev["events"] = [e for e in ev["events"] if not e.get("date") or e["date"] >= today]
    return payload


def _explore(ctx, body):
    """Research the current area again now."""
    (ctx.dir / "force").touch()
    return {"run": True}


ACTIONS = {"explore": _explore}
