"""News headlines from RSS and Atom feeds: free, no AI, no API keys.

  fetch_feed(url, limit=12, max_age_hours=36) -> [{title, url, summary, published}]

Feed text is from the web, so it's reduced to plain text here and treated as data by every prompt that sees it.
"""

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from core.common import http_get

# Some publishers (NPR) refuse unfamiliar user agents on their feeds.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; daily-update/1.0; personal RSS reader)",
           "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}


def _tag(el):
    return el.tag.rsplit("}", 1)[-1]


def _child(el, *names):
    return next((c for c in el if _tag(c) in names), None)


def _text(el):
    return (el.text or "").strip() if el is not None else ""


def plain(text, limit=None):
    """Feed descriptions are often HTML: strip tags and entities, collapse whitespace."""
    text = re.sub(r"(?s)<(script|style)\b.*?</\1>", " ", text or "")
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def _date(value):
    if not value:
        return None
    try:
        d = parsedate_to_datetime(value)  # RSS: RFC 822
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))  # Atom: ISO 8601
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _link(item):
    for c in item:
        if _tag(c) != "link":
            continue
        if c.get("href") and c.get("rel", "alternate") == "alternate":
            return c.get("href")  # Atom
        if c.text and c.text.strip():
            return c.text.strip()  # RSS
    guid = _child(item, "guid")
    return _text(guid) if guid is not None and _text(guid).startswith("http") else ""


def parse(body, limit=12, max_age_hours=36, summary_chars=220):
    root = ET.fromstring(body)
    items = [el for el in root.iter() if _tag(el) in ("item", "entry")]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    out, seen = [], set()
    for item in items:
        title = plain(_text(_child(item, "title")))
        url = _link(item)
        if not title or not url.startswith(("http://", "https://")) or title in seen:
            continue
        published = _date(_text(_child(item, "pubDate", "published", "updated", "date")))
        if published and published < cutoff:
            continue
        seen.add(title)
        summary = plain(_text(_child(item, "description", "summary")), summary_chars)
        out.append({"title": title, "url": url, "summary": summary if summary != title else "",
                    "published": published.isoformat() if published else None})
        if len(out) >= limit:
            break
    return out


def fetch_feed(url, limit=12, max_age_hours=36, summary_chars=220):
    body = http_get(url, as_json=False, timeout=20, headers=HEADERS)
    return parse(body, limit, max_age_hours, summary_chars)
