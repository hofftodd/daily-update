"""Weather for the places you care about (home, a cabin): conditions, local stations, SNOTEL, the week ahead,
and a meteorologist-style AI summary per place.

config.json section options:
  "locations": ["home", "elklake"]     place ids from config "places"
  "forecast_days": 10, "use_nws": true
  "youtube_channels": [...]            optional expert videos for the summary
"""

from sections._places import EXPERT_TAKES, SOURCES, fetch_places, fetch_videos, prompt_locations, prompt_videos

TITLE = "Weather"
ICON = "🌤️"


def gather(ctx):
    cfg = ctx.cfg
    ctx.status("Fetching forecasts, stations and SNOTEL…")
    locations = fetch_places(ctx, cfg.get("locations", []), cfg.get("forecast_days", 10), cfg.get("use_nws", True))
    return {"units": ctx.units, "locations": locations}


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["headline", "locations"],
    "properties": {
        "headline": {"type": "string", "description": "Max ~60 characters: the single most useful weather takeaway across all places for the next few days."},
        "locations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "headline", "now", "outlook", "notes", "access", "expert_takes", "sources"],
                "properties": {
                    "id": {"type": "string", "description": "Location id from the input."},
                    "headline": {"type": "string", "description": "Max ~50 characters. The single most useful takeaway, glanceable."},
                    "now": {"type": "string", "description": "One short sentence on current conditions."},
                    "outlook": {"type": "string", "description": "2-3 short sentences: a forecaster's summary of the coming days - timing, confidence, what to plan around."},
                    "notes": {"type": "array", "items": {"type": "string"}, "description": "0-3 notable items, each under ~40 characters (alerts, frost, wind, storm timing)."},
                    "access": {"type": ["string", "null"], "description": "Cabins: road/highway status you verified this run, under ~90 characters. Null otherwise or if unverified."},
                    "expert_takes": EXPERT_TAKES,
                    "sources": SOURCES,
                },
            },
        },
    },
}

SYSTEM = """You are a meteorologist writing a compact briefing for a personal weather page, read on a phone or desktop.

You get structured forecast data (Open-Meteo) and, for US locations, NOAA's National Weather Service forecast, active \
alerts, and the forecaster's Area Forecast Discussion. Treat the discussion as the best source on timing and confidence. \
Local station readings and SNOTEL sites are ground truth for current conditions. You may also get recent videos from \
weather YouTubers; use only what they say about these locations' area.

The page shows the numbers in charts, so keep text terse and glanceable: no filler, no restating figures, just timing, \
amounts, and what it means for someone planning their day. Units: {units}.

For a home, focus on the next few days: what's changing and when. For a cabin, focus on what an owner needs: \
overnight lows and freeze risk, snowfall and accumulation (use the SNOTEL depth/SWE trends), wind, and access. Search \
for road or highway conditions for any cabin (closures, chain requirements, seasonal gates), preferring sources from \
the last 48 hours; don't search for anything the data already answers. Only state a road condition you found in a \
source during this run; otherwise leave access null. Fill expert_takes from the NWS discussion (name the office) and \
any videos. Give an entry for every location."""


def summarize(ctx, data):
    ctx.status("Gathering expert videos…")
    videos = fetch_videos(ctx.cfg.get("youtube_channels"))
    parts = prompt_locations(data["locations"]) + prompt_videos(videos)
    ctx.status("Writing the AI summary…")
    result, info = ctx.llm(
        call="weather", system=SYSTEM.format(units=ctx.units), user="\n\n".join(parts), schema=SCHEMA,
        description="Publish the finished weather briefing to the page.",
    )
    ids = {l["id"] for l in data["locations"]}
    return {"headline": result["headline"], "locations": {l["id"]: l for l in result["locations"] if l["id"] in ids}}
