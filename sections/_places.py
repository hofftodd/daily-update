"""Shared by the weather and ski sections: fetch everything for a list of places, and lay it out for a prompt."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from core.common import log
from sources import snow, weather


def fetch_place(place, units, days=10, use_nws=True):
    """Forecast, NWS, stations, SNOTEL and snow-forecast.com for one place. Returns (data or None, nws, errors)."""
    data, nws, errs = None, None, []
    try:
        data = weather.fetch_open_meteo(place, units, days)
    except Exception as e:
        errs.append(f"{place['name']}: forecast unavailable ({e})")
    if use_nws:
        nws = weather.fetch_nws(place)
    if data and place.get("stations"):
        data["local_stations"] = weather.fetch_stations(place, units)
    if data and place.get("snotel"):
        try:
            data["snotel"] = weather.fetch_snotel(place["snotel"], units)
        except Exception as e:
            log(f"SNOTEL failed for {place['id']}: {e}")
    if data and place.get("snow_forecast_slug"):
        try:
            data["snow_forecast"] = snow.fetch_snow_forecast(place["snow_forecast_slug"], units)
        except Exception as e:
            log(f"snow-forecast.com failed for {place['id']}: {e}")
    return data, nws, errs


PLACE_KEYS = ("id", "name", "kind", "place", "website", "lat", "lon", "elev_ft", "base_elev_ft", "summit_elev_ft")


def fetch_places(ctx, place_ids, days=10, use_nws=True):
    """All places in parallel. A place whose fetch fails keeps its last good data (marked stale_since)."""
    places = []
    for pid in place_ids:
        p = ctx.place(pid)
        if p:
            places.append(p)
        else:
            ctx.error(f"Unknown place '{pid}' in config.json")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda p: fetch_place(p, ctx.units, days, use_nws), places))

    prev = {l["id"]: l for l in ((ctx.prev.get("data") or {}).get("locations") or [])}
    out = []
    for p, (data, nws, errs) in zip(places, results):
        for e in errs:
            ctx.error(e)
        old = prev.get(p["id"], {})
        if data is None and old.get("current"):
            data = {k: v for k, v in old.items() if k not in PLACE_KEYS}
            data["stale_since"] = old.get("stale_since") or ctx.prev.get("generated_at")
        elif data is not None and p.get("snotel") and not data.get("snotel") and old.get("snotel"):
            data["snotel"] = old["snotel"]  # each row carries its own observation time
        nws = nws or {}
        out.append({
            **{k: p.get(k) for k in PLACE_KEYS},
            **(data or {}),
            "alerts": nws.get("alerts", []),
            "nws_periods": nws.get("periods", []),
            "nws_office": nws.get("office"),
            # Keys starting with "_" stay on the server: the page doesn't need the full discussion text.
            "_nws_discussion": nws.get("discussion"),
        })
    return out


def prompt_locations(locations, extra=None):
    """Prompt blocks for each place, plus each NWS office's forecast discussion once."""
    now = datetime.now().astimezone()
    parts = [f"Current local time: {now:%A %Y-%m-%d %H:%M %Z}\n"]
    seen = set()
    for loc in locations:
        summary = {
            "id": loc["id"], "name": loc["name"], "kind": loc["kind"], "place": loc.get("place"),
            "lat": loc["lat"], "lon": loc["lon"], "resort_website": loc.get("website"),
            "elev_ft": loc.get("elev_ft"), "base_elev_ft": loc.get("base_elev_ft"), "summit_elev_ft": loc.get("summit_elev_ft"),
            "open_meteo": {k: loc.get(k) for k in ("current", "base_current", "daily", "snow_models", "snow_7d", "units") if loc.get(k)},
            "nws_forecast": loc.get("nws_periods"),
            "nws_alerts": loc.get("alerts"),
            "snow_forecast_com": loc.get("snow_forecast"),
            "local_stations": loc.get("local_stations"),
            "snotel": loc.get("snotel"),
            **(extra(loc) if extra else {}),
        }
        parts.append(f"<location>\n{json.dumps({k: v for k, v in summary.items() if v not in (None, [], {})}, separators=(',', ':'))}\n</location>")
        office = loc.get("nws_office")
        if loc.get("_nws_discussion") and office not in seen:
            seen.add(office)
            parts.append(f"<forecast_discussion office=\"{office}\">\n{loc['_nws_discussion']}\n</forecast_discussion>")
    return parts


def prompt_videos(videos):
    return [
        f"<video channel=\"{v['channel']}\" published=\"{v['published']}\" url=\"{v['url']}\">\n"
        f"Title: {v['title']}\nDescription: {v['description']}\nTranscript: {v['transcript'] or '(no transcript available)'}\n</video>"
        for v in videos
    ]


def fetch_videos(channels):
    videos = []
    for channel in channels or []:
        try:
            videos += snow.fetch_youtube(channel, channel.get("max_age_days", 7), channel.get("max_videos", 7))
        except Exception as e:
            log(f"YouTube feed failed for {channel['name']}: {e}")
    return videos


def prompt_blogs(posts):
    return [
        f"<blog_post blog=\"{p['blog']}\" published=\"{p['published']}\" url=\"{p['url']}\">\n"
        f"Title: {p['title']}\n{p['text']}\n</blog_post>"
        for p in posts
    ]


def fetch_blogs(blogs):
    posts = []
    for blog in blogs or []:
        try:
            posts += snow.fetch_blog(blog, blog.get("max_age_days", 10), blog.get("max_posts", 3))
        except Exception as e:
            log(f"Blog feed failed for {blog['name']}: {e}")
    return posts


NULLABLE_NUM = {"type": ["number", "null"]}
NULLABLE_STR = {"type": ["string", "null"]}

EXPERT_TAKES = {
    "type": "array",
    "description": "What named forecasters (the NWS discussion - name the office, OpenSnow, a YouTube meteorologist) say about THIS place. Only takes that actually cover this area.",
    "items": {
        "type": "object", "additionalProperties": False, "required": ["source", "take", "url"],
        "properties": {"source": {"type": "string"}, "take": {"type": "string", "description": "Under ~90 characters."}, "url": NULLABLE_STR},
    },
}
SOURCES = {
    "type": "array",
    "description": "Only pages you actually retrieved during this run.",
    "items": {
        "type": "object", "additionalProperties": False, "required": ["title", "url"],
        "properties": {"title": {"type": "string"}, "url": {"type": "string"}},
    },
}
