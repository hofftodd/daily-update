"""Shared by the daily and local sections: where you are right now, and a one-line weather summary for prompts."""

from sources import location as locate

WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "showers", 81: "showers", 82: "heavy showers", 85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail",
}


def home(ctx):
    lc = ctx.cfg.get("location") or {}
    if lc.get("home"):
        return lc["home"]
    place = ctx.place(lc.get("home_place", "home")) or next((p for p in ctx.config.get("places", []) if p.get("kind") == "home"), None)
    return {"name": place["name"], "lat": place["lat"], "lon": place["lon"]} if place else {"name": "Home", "lat": 0, "lon": 0}


def locate_here(ctx):
    """The freshest of the Mac's and phone's fixes (falling back to home). Returns (location, label)."""
    loc = locate.current_location({**(ctx.cfg.get("location") or {}), "home": home(ctx)})
    return loc, locate.place_label(loc)


def location_summary(loc, label):
    """What the page shows about the current location."""
    return {**{k: loc.get(k) for k in ("lat", "lon", "source", "time", "accuracy_m")}, "label": label}


def weather_line(w):
    if not w:
        return "unavailable"
    c, d = w["current"], w["daily"][0]
    wet = [h for h in w["hourly"] if (h.get("precipitation_probability") or 0) >= 50]
    rain = f", {WMO.get(wet[0]['weather_code'], 'precip')} likely from {wet[0]['time'][11:16]}" if wet else ""
    return (
        f"now {round(c['temperature_2m'])}° {WMO.get(c['weather_code'], '')}, high {round(d['temperature_2m_max'])}° "
        f"low {round(d['temperature_2m_min'])}°, {d['precipitation_probability_max']}% precip chance, "
        f"gusts to {round(d['wind_gusts_10m_max'])}{rain}"
    )
