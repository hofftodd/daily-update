"""AI cost tracking: every model call is logged (failed ones too, since they're billed) to data/usage.jsonl."""

import json
import threading
from datetime import datetime, timedelta, timezone

from core.common import DATA, log

USAGE_LOG = DATA / "usage.jsonl"
# $ per million tokens: (input, output, cache read). Web search is $10 per 1,000 searches; page fetches are token-only.
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}
SEARCH_PRICE = 0.01
TYPICAL_RUN = {"claude-sonnet-5-5": 0.25, "claude-opus-5-5": 1.10, "claude-haiku-4-5": 0.08}  # until there's history
_lock = threading.Lock()


def cost(model, u, provider="anthropic"):
    if provider != "anthropic":
        return 0.0  # local models are free to run
    p_in, p_out, p_cache = PRICES.get(model, PRICES["claude-opus-5-5"])
    return round((u["input"] * p_in + u["output"] * p_out + u["cache_read"] * p_cache) / 1e6 + u["searches"] * SEARCH_PRICE, 4)


def record(section_id, call, usage, ok, provider="anthropic"):
    if not usage["requests"]:
        return  # failed before anything reached the model (no key, no network): nothing billed
    entry = {
        "time": datetime.now(timezone.utc).isoformat(), "section": section_id, "call": call, "provider": provider,
        "ok": ok, **usage, "cost": cost(usage["model"], usage, provider),
    }
    with _lock:
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    log(f"[{section_id}] {call} cost ${entry['cost']:.3f}")


def _rows():
    if not USAGE_LOG.exists():
        return []
    rows = []
    for line in USAGE_LOG.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def summary(sections):
    """Totals, a 14-day chart, and a monthly projection per section at its current settings.
    `sections` is a list of (id, title, model, provider, runs_per_day)."""
    rows = _rows()
    now = datetime.now().astimezone()
    local = lambda r: datetime.fromisoformat(r["time"]).astimezone()
    total = lambda rs: round(sum(r["cost"] for r in rs), 2)
    daily = []
    for i in range(13, -1, -1):
        day = (now - timedelta(days=i)).date()
        daily.append({"date": day.isoformat(), "cost": total([r for r in rows if local(r).date() == day])})

    projections = []
    for sid, title, model, provider, per_day in sections:
        mine = [r for r in rows if r.get("section") == sid]
        # A run can be several calls (a briefing plus research); group calls that happened close together.
        runs, last = [], None
        for r in mine:
            if not r.get("ok"):
                continue
            t = local(r)
            if last and t - last < timedelta(minutes=20) and runs:
                runs[-1] += r["cost"]
            else:
                runs.append(r["cost"])
            last = t
        recent = runs[-5:]
        per_run = 0.0 if provider != "anthropic" else (round(sum(recent) / len(recent), 3) if recent else TYPICAL_RUN.get(model, 0.5))
        projections.append({
            "section": sid, "title": title, "model": model, "provider": provider,
            "per_run": per_run, "per_day": per_day, "per_month": round(per_run * per_day * 30, 2),
            "based_on": len(recent), "month": total([r for r in mine if (local(r).year, local(r).month) == (now.year, now.month)]),
        })
    return {
        "today": total([r for r in rows if local(r).date() == now.date()]),
        "week": total([r for r in rows if local(r) > now - timedelta(days=7)]),
        "month": total([r for r in rows if (local(r).year, local(r).month) == (now.year, now.month)]),
        "all_time": total(rows),
        "count": len(rows),
        "daily": daily,
        "recent": rows[-10:][::-1],
        "sections": projections,
        "projected_month": round(sum(p["per_month"] for p in projections), 2),
    }
