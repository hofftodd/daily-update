"""Weather data: Open-Meteo forecasts (with several global models' snowfall for mountains), NOAA/NWS forecasts,
alerts and discussions, nearby mesonet stations, and NRCS SNOTEL.

Places come from config.json "places"; `kind` is home, cabin or mountain.
"""

from datetime import datetime, timedelta, timezone

from core.common import http_get, log

SNOW_MODELS = {
    "ecmwf_ifs025": "ECMWF",
    "gfs_seamless": "GFS",
    "icon_seamless": "ICON",
    "gem_seamless": "GEM",
}

CURRENT_VARS = (
    "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,"
    "weather_code,wind_speed_10m,wind_gusts_10m,wind_direction_10m,is_day,snow_depth"
)
DAILY_VARS = (
    "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum,"
    "precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,sunrise,sunset"
)


def unit_params(units):
    if units == "metric":
        return {}
    return {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch"}


def ft_to_m(ft):
    return round(ft * 0.3048)


# ---------------------------------------------------------------- Open-Meteo


def open_meteo(loc, units, elevation_ft=None, **extra):
    params = {
        "latitude": loc["lat"],
        "longitude": loc["lon"],
        "timezone": "auto",
        **unit_params(units),
        **extra,
    }
    if elevation_ft is not None:
        params["elevation"] = ft_to_m(elevation_ft)
    return http_get("https://api.open-meteo.com/v1/forecast", params)


def daily_rows(daily):
    keys = [k for k in daily if k != "time"]
    return [{"date": d, **{k: daily[k][i] for k in keys}} for i, d in enumerate(daily["time"])]


def fetch_open_meteo(loc, units, days):
    # Mountains are forecast at summit elevation; Open-Meteo downscales temps/snow to it.
    elev = loc.get("summit_elev_ft") if loc["kind"] == "mountain" else loc.get("elev_ft")
    data = open_meteo(loc, units, elev, current=CURRENT_VARS, daily=DAILY_VARS, forecast_days=days)
    result = {
        "timezone": data["timezone"],
        "current": data["current"],
        "units": {**data["current_units"], **data["daily_units"]},
        "daily": daily_rows(data["daily"]),
    }
    if loc["kind"] != "mountain":
        return result

    if loc.get("base_elev_ft"):
        base = open_meteo(loc, units, loc["base_elev_ft"], current=CURRENT_VARS)
        result["base_current"] = base["current"]

    # Snowfall from several global models: the spread is the honest uncertainty.
    models = open_meteo(
        loc, units, elev, daily="snowfall_sum", models=",".join(SNOW_MODELS), forecast_days=days
    )["daily"]
    snow = []
    for i, date in enumerate(models["time"]):
        by_model = {
            label: models.get(f"snowfall_sum_{key}", [None] * (i + 1))[i]
            for key, label in SNOW_MODELS.items()
        }
        vals = [v for v in by_model.values() if v is not None]
        snow.append({
            "date": date,
            "models": by_model,
            "mean": round(sum(vals) / len(vals), 2) if vals else None,
            "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
        })
    result["snow_models"] = snow
    week = snow[:7]
    result["snow_7d"] = {
        label: round(sum(d["models"][label] or 0 for d in week), 1)
        for label in SNOW_MODELS.values()
        if any(d["models"][label] is not None for d in week)
    }
    return result


# ---------------------------------------------------------------- NWS (US only)


def fetch_nws(loc):
    """Forecast text, active alerts, and the forecaster discussion. Returns None outside the US."""
    try:
        point = http_get(f"https://api.weather.gov/points/{loc['lat']:.4f},{loc['lon']:.4f}")["properties"]
    except Exception:
        return None
    nws = {"office": point.get("cwa"), "periods": [], "alerts": [], "discussion": None}
    try:
        periods = http_get(point["forecast"])["properties"]["periods"]
        nws["periods"] = [
            {"name": p["name"], "short": p["shortForecast"], "detail": p["detailedForecast"]}
            for p in periods[:8]
        ]
    except Exception as e:
        log(f"NWS forecast failed for {loc['id']}: {e}")
    try:
        alerts = http_get("https://api.weather.gov/alerts/active", {"point": f"{loc['lat']:.4f},{loc['lon']:.4f}"})
        nws["alerts"] = [
            {
                "event": a["properties"]["event"],
                "headline": a["properties"].get("headline"),
                "severity": a["properties"].get("severity"),
                "ends": a["properties"].get("ends") or a["properties"].get("expires"),
            }
            for a in alerts.get("features", [])
        ]
    except Exception as e:
        log(f"NWS alerts failed for {loc['id']}: {e}")
    try:
        products = http_get(f"https://api.weather.gov/products/types/AFD/locations/{nws['office']}")["@graph"]
        if products:
            nws["discussion"] = http_get(products[0]["@id"])["productText"]
    except Exception as e:
        log(f"NWS discussion failed for {loc['id']}: {e}")
    return nws


# ---------------------------------------------------------------- local stations (NOAA / MADIS)


def fetch_station(station_id, units):
    """Recent observations from a NOAA-listed station (ASOS, CWOP citizen stations, MesoWest, RAWS, ODOT...).

    Many mesonet sensors leave fields blank on some reports, so each value is the most recent non-empty one."""
    feats = http_get(f"https://api.weather.gov/stations/{station_id}/observations", {"limit": 24})["features"]
    obs = [f["properties"] for f in feats]
    if not obs:
        raise RuntimeError("no observations")

    def latest(key):
        for o in obs:
            v = (o.get(key) or {}).get("value")
            if v is not None:
                return v, o["timestamp"]
        return None, None

    recent = [o for o in obs if datetime.fromisoformat(o["timestamp"]) > datetime.now(timezone.utc) - timedelta(hours=3)]
    gusts = [(o.get("windGust") or {}).get("value") for o in recent]
    gusts = [g for g in gusts if g is not None]
    temp_c, temp_time = latest("temperature")
    wind_kmh, _ = latest("windSpeed")
    rh, _ = latest("relativeHumidity")
    wdir, _ = latest("windDirection")
    imperial = units != "metric"
    conv_t = (lambda c: round(c * 9 / 5 + 32, 1)) if imperial else (lambda c: round(c, 1))
    conv_w = (lambda k: round(k / 1.609)) if imperial else (lambda k: round(k))
    return {
        "id": station_id,
        "name": obs[0].get("stationName") or station_id,
        "elev_ft": round(obs[0]["elevation"]["value"] * 3.281) if (obs[0].get("elevation") or {}).get("value") is not None else None,
        "time": temp_time or obs[0]["timestamp"],
        "temp": conv_t(temp_c) if temp_c is not None else None,
        "humidity": round(rh) if rh is not None else None,
        "wind": conv_w(wind_kmh) if wind_kmh is not None else None,
        "gust_3h": conv_w(max(gusts)) if gusts else None,
        "wind_dir": wdir,
    }


def fetch_stations(loc, units):
    max_age_minutes = 90 if loc["kind"] == "home" else 180  # mountain mesonets report hourly or less
    stations = []
    for sid in loc.get("stations", []):
        try:
            st = fetch_station(sid, units)
        except Exception as e:
            log(f"station {sid} failed: {e}")
            continue
        age = datetime.now(timezone.utc) - datetime.fromisoformat(st["time"]) if st["time"] else None
        st["stale"] = age is None or age > timedelta(minutes=max_age_minutes)
        stations.append(st)
    fresh = sorted(s["temp"] for s in stations if not s["stale"] and s["temp"] is not None)
    summary = None
    if fresh:
        mid = len(fresh) // 2
        median = fresh[mid] if len(fresh) % 2 else (fresh[mid - 1] + fresh[mid]) / 2
        summary = {"median_temp": round(median, 1), "min_temp": fresh[0], "max_temp": fresh[-1], "count": len(fresh)}
    return {"stations": stations, "summary": summary}


# ---------------------------------------------------------------- SNOTEL (NRCS)

AWDB = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
AWDB_TZ = "-08:00"


def fetch_snotel(triplets, units):
    """NRCS SNOTEL telemetry: temperature, snow depth, snow water equivalent, precipitation.
    AWDB timestamps are local standard time; values are reported in inches / degF."""
    ids = ",".join(triplets)
    meta = {m["stationTriplet"]: m for m in http_get(f"{AWDB}/stations", {"stationTriplets": ids, "returnStationElements": "false"})}
    now = datetime.now()
    # The DAILY endpoint errors for SNWD/WTEQ, so the 14-day trend is built from hourly data too.
    hourly = http_get(f"{AWDB}/data", {
        "stationTriplets": ids, "elements": "SNWD,WTEQ,TOBS,PREC", "duration": "HOURLY",
        "beginDate": (now - timedelta(days=14)).strftime("%Y-%m-%d %H:00"), "endDate": (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:00"),
    })
    metric = units == "metric"
    to_len = (lambda v: round(v * 2.54, 1)) if metric else (lambda v: v)
    to_t = (lambda f: round((f - 32) * 5 / 9, 1)) if metric else (lambda f: f)

    out = []
    for st in hourly:
        trip = st["stationTriplet"]
        series = {e["stationElement"]["elementCode"]: [v for v in e["values"] if v.get("value") is not None] for e in st["data"]}

        def last(code):
            vals = series.get(code) or []
            return (vals[-1]["value"], vals[-1]["date"]) if vals else (None, None)

        def change(code, hours):
            vals = series.get(code) or []
            if not vals:
                return None
            end = datetime.strptime(vals[-1]["date"], "%Y-%m-%d %H:%M")
            past = [v for v in vals if datetime.strptime(v["date"], "%Y-%m-%d %H:%M") <= end - timedelta(hours=hours)]
            return round(vals[-1]["value"] - past[-1]["value"], 1) if past else None

        def precip_since(hours):
            # PREC is a water-year accumulation that resets Oct 1; sum the increases instead of differencing.
            vals = series.get("PREC") or []
            if not vals:
                return None
            end = datetime.strptime(vals[-1]["date"], "%Y-%m-%d %H:%M")
            window = [v["value"] for v in vals if datetime.strptime(v["date"], "%Y-%m-%d %H:%M") >= end - timedelta(hours=hours)]
            return round(sum(max(0, b - a) for a, b in zip(window, window[1:])), 2)

        def iso(stamp):  # AWDB reports local standard time; Pacific stations are UTC-8 year round
            return f"{stamp.replace(' ', 'T')}:00{AWDB_TZ}" if stamp else None

        depth, depth_time = last("SNWD")
        temp, temp_time = last("TOBS")
        swe, _ = last("WTEQ")
        temps_24h = [v["value"] for v in (series.get("TOBS") or [])[-24:]]
        per_day = {}
        for v in series.get("SNWD") or []:
            per_day[v["date"][:10]] = v["value"]  # last reading of each day
        m = meta.get(trip, {})
        out.append({
            "id": trip,
            "name": m.get("name", trip),
            "elev_ft": m.get("elevation"),
            "time": iso(temp_time or depth_time),
            "temp": to_t(temp) if temp is not None else None,
            "temp_min_24h": to_t(min(temps_24h)) if temps_24h else None,
            "snow_depth": to_len(depth) if depth is not None else None,
            "depth_change_24h": to_len(change("SNWD", 24)) if change("SNWD", 24) is not None else None,
            "swe": to_len(swe) if swe is not None else None,
            "precip_72h": to_len(precip_since(72)) if precip_since(72) is not None else None,
            "depth_14d": [{"date": d, "value": to_len(v)} for d, v in sorted(per_day.items())],
            "url": f"https://wcc.sc.egov.usda.gov/nwcc/site?sitenum={trip.split(':')[0]}",
        })
    order = {t: i for i, t in enumerate(triplets)}
    return sorted(out, key=lambda x: order.get(x["id"], 99))




# ---------------------------------------------------------------- quick local forecast (Daily Update)

QUICK_CURRENT = "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,wind_gusts_10m,is_day"
QUICK_HOURLY = "temperature_2m,precipitation_probability,weather_code"
QUICK_DAILY = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,snowfall_sum,wind_gusts_10m_max,uv_index_max,sunrise,sunset"


def fetch_quick(lat, lon, units="imperial"):
    """Today's weather anywhere (no key needed): current conditions, the next 15 hours, and 3 days."""
    params = {
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
        "current": QUICK_CURRENT, "hourly": QUICK_HOURLY, "daily": QUICK_DAILY, **unit_params(units),
    }
    d = http_get("https://api.open-meteo.com/v1/forecast", params)
    now_hour = d["current"]["time"][:13]
    times = d["hourly"]["time"]
    start = next((i for i, t in enumerate(times) if t[:13] >= now_hour), 0)
    hourly = [
        {"time": times[i], **{k: d["hourly"][k][i] for k in d["hourly"] if k != "time"}}
        for i in range(start, min(start + 15, len(times)))
    ]
    return {"timezone": d["timezone"], "current": d["current"], "hourly": hourly, "daily": daily_rows(d["daily"])}
