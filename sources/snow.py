"""Mountain sources: avalanche center forecasts, snow-forecast.com's summit table, and YouTube forecasters."""

from datetime import datetime, timedelta, timezone

from core.common import CACHE, http_get, log

# ---------------------------------------------------------------- avalanche forecast


def strip_html(text):
    import html as htmllib
    import re

    text = re.sub(r"</p>\s*<p>|<br\s*/?>", "\n", text or "")
    return htmllib.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ").strip()


def fetch_avalanche(av):
    """The avalanche center's own published forecast, via the National Avalanche Center API that
    powers the forecast pages on the center's website (e.g. coavalanche.org). Shown verbatim."""
    product = http_get(
        "https://api.avalanche.org/v2/public/product",
        {"type": "forecast", "center_id": av["center_id"], "zone_id": av["zone_id"]},
    )
    expires = product.get("expires_time")
    # No expiry time counts as expired: never show a forecast we can't confirm is current.
    expired = not expires or datetime.fromisoformat(expires) <= datetime.now(timezone.utc)
    meta = {
        "label": av.get("label"),
        "zone": ", ".join(z["name"] for z in product.get("forecast_zone") or []),
        "center": (product.get("avalanche_center") or {}).get("name"),
        "expires": expires,
        "expired": expired,
        "link": av.get("link"),
    }
    if expired:
        return meta  # drop danger ratings, problems and text from an expired forecast
    danger ={d["valid_day"]: {k: d[k] for k in ("upper", "middle", "lower")} for d in product.get("danger") or []}
    problems = [
        {
            "name": p["name"],
            "likelihood": p.get("likelihood"),
            "size": p.get("size"),
            "location": p.get("location") or [],
            "rank": p.get("rank"),
        }
        for p in sorted(product.get("forecast_avalanche_problems") or [], key=lambda p: p.get("rank") or 9)
    ]
    return {
        **meta,
        "product_type": product.get("product_type"),
        "published": product.get("published_time"),
        "author": product.get("author"),
        "danger": danger,
        "problems": problems,
        "bottom_line": strip_html(product.get("bottom_line")),
        "link": av.get("link"),
    }


# ---------------------------------------------------------------- snow-forecast.com


def fetch_snow_forecast(slug, units):
    """Scrape snow-forecast.com's 6-day summit table (AM / PM / night columns, metric on the page)."""
    import html as htmllib
    import re

    page = http_get(f"https://www.snow-forecast.com/resorts/{slug}/6day/top", as_json=False)

    def row(name):
        m = re.search(rf'data-row="{name}".*?</tr>', page, re.S)
        if not m:
            return []
        cells = re.findall(r"<td[^>]*>(.*?)</td>", m.group(0), re.S)
        return [" ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", c)).split()) for c in cells]

    def num(s):
        try:
            return float(s)
        except (TypeError, ValueError):
            return 0.0 if s in ("—", "-", "") else None

    days_row = re.search(r'data-row="days".*?</tr>', page, re.S).group(0)
    spans = [int(n) for n in re.findall(r'<td[^>]*colspan="(\d+)"', days_row)]
    times, snow, rain = row("time"), row("snow"), row("rain")
    freeze, tmax, phrases = row("freezing-level"), row("temperature-max"), row("phrases")
    # each day spans up to 3 columns (AM / PM / night); today may have fewer
    day_names = [d for d, n in zip(row("days"), spans) for _ in range(n)]
    imperial = units != "metric"
    periods = []
    for i, t in enumerate(times):
        cm, mm, fl, c = (num(x[i]) if i < len(x) else None for x in (snow, rain, freeze, tmax))
        periods.append({
            "day": day_names[i] if i < len(day_names) else None,
            "period": t,
            "snow": round(cm / 2.54, 1) if imperial and cm is not None else cm,
            "rain": round(mm / 25.4, 2) if imperial and mm is not None else mm,
            "freezing_level": round(fl * 3.281, -2) if imperial and fl is not None else fl,
            "temp_max": round(c * 9 / 5 + 32) if imperial and c is not None else c,
            "summary": phrases[i] if i < len(phrases) else None,
        })
    return {
        "url": f"https://www.snow-forecast.com/resorts/{slug}/6day/top",
        "units": "in / ft / F" if imperial else "cm / m / C",
        "periods": periods,
        "total_snow": round(sum(p["snow"] or 0 for p in periods), 1),
    }


# ---------------------------------------------------------------- YouTube forecasters


TRANSCRIPTS = CACHE / "transcripts"
_youtube_blocked = False


def get_transcript(video_id):
    """Transcripts never change, so each is fetched from YouTube once and cached on disk."""
    global _youtube_blocked
    cached = TRANSCRIPTS / f"{video_id}.txt"
    if cached.exists():
        return cached.read_text()
    if _youtube_blocked:
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        text = " ".join(s.text for s in YouTubeTranscriptApi().fetch(video_id))
    except Exception as e:
        first_line = (str(e).strip().splitlines() or [type(e).__name__])[0]
        if "block" in str(e).lower():
            _youtube_blocked = True  # don't keep hammering YouTube this run
            log(f"YouTube is blocking transcript requests; skipping the rest this run ({video_id})")
        else:
            log(f"no transcript for {video_id}: {first_line}")
        return None
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    cached.write_text(text)
    return text


def fetch_blog(blog, max_age_days=10, max_posts=3):
    """Recent posts from a forecaster's blog, full text, via its Atom feed (Shopify blogs serve one at <blog url>.atom)."""
    import xml.etree.ElementTree as ET

    ns = {"a": "http://www.w3.org/2005/Atom"}
    feed = ET.fromstring(http_get(blog.get("feed") or blog["url"].rstrip("/") + ".atom", as_json=False))
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    posts = []
    for entry in feed.findall("a:entry", ns):
        published = datetime.fromisoformat(entry.find("a:published", ns).text)
        if published < cutoff or len(posts) >= max_posts:
            continue
        link = entry.find("a:link[@rel='alternate']", ns)
        posts.append({
            "blog": blog["name"],
            "title": entry.find("a:title", ns).text,
            "published": published.isoformat(),
            "url": link.get("href") if link is not None else blog["url"],
            "text": strip_html(entry.findtext("a:content", "", ns))[:12000],
        })
    return posts


def fetch_youtube(channel, max_age_days=7, max_videos=7):
    """Recent videos from a forecaster's channel, with transcripts when YouTube provides them."""
    import xml.etree.ElementTree as ET

    ns = {"a": "http://www.w3.org/2005/Atom", "m": "http://search.yahoo.com/mrss/", "yt": "http://www.youtube.com/xml/schemas/2015"}
    feed = ET.fromstring(http_get("https://www.youtube.com/feeds/videos.xml", {"channel_id": channel["channel_id"]}, as_json=False))
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    videos = []
    for entry in feed.findall("a:entry", ns):
        published = datetime.fromisoformat(entry.find("a:published", ns).text)
        if published < cutoff or len(videos) >= max_videos:
            continue
        video_id = entry.find("yt:videoId", ns).text
        video = {
            "channel": channel["name"],
            "title": entry.find("a:title", ns).text,
            "published": published.isoformat(),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "description": (entry.find("m:group/m:description", ns).text or "")[:1500],
            "transcript": None,
        }
        video["transcript"] = get_transcript(video_id)
        videos.append(video)
    return videos


