"""Ski: a regional snow outlook, your home mountain in depth, the avalanche forecast, and a quick look at other
mountains, with an AI summary that checks resort status, snow reports and expert forecasts.

config.json section options:
  "home_mountain": "bachelor", "mountains": ["hoodoo", ...]    place ids (kind "mountain")
  "avalanche": {"center_id": "COAA", "zone_id": 2470, "label": "...", "link": "..."}
  "youtube_channels": [{"name", "channel_id", "max_age_days", "max_videos"}]
  "forecast_blogs": [{"name", "url", "feed" (optional; default <url>.atom), "max_age_days", "max_posts"}]
"""

from sections._places import (
    EXPERT_TAKES, NULLABLE_NUM, NULLABLE_STR, SOURCES, fetch_blogs, fetch_places, fetch_videos, prompt_blogs,
    prompt_locations, prompt_videos,
)
from sources import snow

TITLE = "Ski"
ICON = "🎿"


def gather(ctx):
    cfg = ctx.cfg
    home = cfg.get("home_mountain")
    ids = ([home] if home else []) + [m for m in cfg.get("mountains", []) if m != home]
    ctx.status("Fetching mountain forecasts…")
    locations = fetch_places(ctx, ids, cfg.get("forecast_days", 10), cfg.get("use_nws", True))
    avalanche = None
    if cfg.get("avalanche"):
        try:
            avalanche = snow.fetch_avalanche(cfg["avalanche"])
        except Exception as e:
            ctx.error(f"Avalanche forecast unavailable: {e}")
            avalanche = (ctx.prev.get("data") or {}).get("avalanche")
    return {"units": ctx.units, "home_mountain": home, "locations": locations, "avalanche": avalanche}


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["regional_outlook", "mountains"],
    "properties": {
        "regional_outlook": {
            "type": "object",
            "additionalProperties": False,
            "required": ["headline", "summary", "storm_character", "peak_day", "confidence", "days"],
            "description": "The big-picture snow story for these mountains over the next 7 days, read at a glance.",
            "properties": {
                "headline": {"type": "string", "description": "Max ~45 characters, punchy, like a ski-town forecaster: 'Heavy snow inbound midweek', 'Dry and mild all week'."},
                "summary": {"type": "string", "description": "1-2 short sentences: what's approaching, when it arrives and peaks, how much, snow quality, snow levels."},
                "storm_character": {"type": "string", "enum": ["none", "cold powder", "mixed", "heavy wet", "rain/snow mix"]},
                "peak_day": {**NULLABLE_STR, "description": "ISO date (YYYY-MM-DD) of the heaviest snow day, or null if none."},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                "days": {
                    "type": "array",
                    "description": "One entry per day for the next 7 days, starting today, for the home mountain's area.",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["date", "intensity", "quality", "snow_level_ft"],
                        "properties": {
                            "date": {"type": "string", "description": "YYYY-MM-DD"},
                            "intensity": {"type": "string", "enum": ["none", "light", "moderate", "heavy"], "description": "light < 3 in, moderate 3-8 in, heavy > 8 in at summit."},
                            "quality": {"type": "string", "enum": ["none", "cold powder", "medium", "heavy wet", "rain/mix"]},
                            "snow_level_ft": {**NULLABLE_NUM, "description": "Approximate snow level when precipitating, else null."},
                        },
                    },
                },
            },
        },
        "mountains": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "headline", "now", "outlook", "notes", "snow_report", "expected_snow_7d", "best_day", "expert_takes", "sources"],
                "properties": {
                    "id": {"type": "string", "description": "Location id from the input."},
                    "headline": {"type": "string", "description": "Max ~50 characters. The single most useful takeaway."},
                    "now": {"type": "string", "description": "One short sentence on current conditions."},
                    "outlook": {"type": "string", "description": "1-3 short sentences on the coming days."},
                    "notes": {"type": "array", "items": {"type": "string"}, "description": "0-3 items under ~40 characters."},
                    "snow_report": {
                        "anyOf": [
                            {"type": "null"},
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["status", "base_depth_in", "new_24h_in", "new_7d_in", "lifts_open", "trails_open", "as_of"],
                                "properties": {
                                    "status": {"type": "string", "description": "e.g. 'Open', 'Closed - opens Nov 21 (target)', 'Weekends only'."},
                                    "base_depth_in": NULLABLE_NUM,
                                    "new_24h_in": NULLABLE_NUM,
                                    "new_7d_in": NULLABLE_NUM,
                                    "lifts_open": NULLABLE_STR,
                                    "trails_open": NULLABLE_STR,
                                    "as_of": NULLABLE_STR,
                                },
                            },
                        ],
                        "description": "From the resort's own report when available; null if you couldn't find one.",
                    },
                    "expected_snow_7d": {
                        "anyOf": [
                            {"type": "null"},
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["low_in", "high_in", "confidence"],
                                "properties": {
                                    "low_in": {"type": "number"},
                                    "high_in": {"type": "number"},
                                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                                },
                            },
                        ],
                        "description": "Your best-estimate range of summit snowfall over the next 7 days.",
                    },
                    "best_day": {**NULLABLE_STR, "description": "Best upcoming day to ski, or null if closed / nothing stands out."},
                    "expert_takes": EXPERT_TAKES,
                    "sources": SOURCES,
                },
            },
        },
    },
}

SYSTEM = """You are a mountain meteorologist writing a compact ski briefing for a personal page, read on a phone or desktop.

You get structured forecast data (Open-Meteo at summit elevation, with several global models' snowfall), NOAA's National \
Weather Service forecast, alerts and Area Forecast Discussion (the best source on timing and confidence), \
snow-forecast.com's 6-day summit forecast, and possibly recent videos (with transcripts) from mountain-weather YouTubers \
and recent posts from forecasters' blogs such as Powderchasers. Those videos and posts usually cover the whole West or \
the whole continent: read each one for what it says about the Pacific Northwest (the Oregon and Washington Cascades, \
Mt. Hood, Central Oregon) and above all {home}, and use only that. Note storm timing, totals and snow quality they \
call for there, and name the forecaster in expert_takes with the post's url. A post that doesn't mention this area \
tells you nothing about it; skip it rather than stretching a Rockies or Sierra forecast to fit.

The data has no resort operating status or snow reports, so look them up: search for each ski area's current status \
and snow report (opening date if closed; local news often reports opening dates) and expert mountain forecasts such as \
OpenSnow. Prefer sources from the last 48 hours and ignore stale pages. Only state a status, opening date or snow depth \
that you found in a source during this run; if you couldn't verify it, write "Status unknown" (or null) instead of guessing.

When the snowfall models disagree, say so and lean on the discussion and expert forecasts to judge which is more likely. \
The page shows the numbers in charts; keep text terse and glanceable: timing, amounts, snow quality, and what it means \
for someone deciding when and where to ski. Units: {units}.

Lead with the regional_outlook: the snow story approaching these mountains over the next 7 days, judged from all \
sources together. Name the timing and peak, and say what kind of snow it is (cold dry powder versus heavy wet snow \
versus rain at the base) using snow levels and temperatures. If nothing is coming, say so plainly.

Go deepest on the home mountain ({home}); for the others a quick status and snow outlook is enough. Give an entry for \
every mountain."""


def summarize(ctx, data):
    ctx.status("Gathering expert videos and forecasts…")
    videos = fetch_videos(ctx.cfg.get("youtube_channels"))
    posts = fetch_blogs(ctx.cfg.get("forecast_blogs"))
    home = data.get("home_mountain")
    parts = prompt_locations(data["locations"], extra=lambda l: {"home_mountain": l["id"] == home})
    av = data.get("avalanche")
    if av and not av.get("expired"):
        parts.append(f"<avalanche_forecast zone=\"{av.get('zone')}\">\n{av.get('bottom_line')}\n</avalanche_forecast>")
    parts += prompt_videos(videos) + prompt_blogs(posts)
    home_name = next((l["name"] for l in data["locations"] if l["id"] == home), home)
    ctx.status("Writing the AI summary…")
    result, info = ctx.llm(
        call="ski", system=SYSTEM.format(units=ctx.units, home=home_name), user="\n\n".join(parts), schema=SCHEMA,
        description="Publish the finished ski briefing to the page.",
    )
    ids = {l["id"] for l in data["locations"]}
    return {
        "outlook": result["regional_outlook"],
        "mountains": {m["id"]: m for m in result["mountains"] if m["id"] in ids},
    }
