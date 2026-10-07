"""Persistent reminders for the Daily Update: pulled out of mail and calendar by the briefing, or added by hand.
The store lives in the section's data folder."""

import hashlib
import re
import secrets
import threading
from datetime import date, datetime, timedelta, timezone

from core.common import read_json, write_atomic

PRIORITY = {"high": 0, "medium": 1, "low": 2}
# The briefing merges on a worker thread while the page checks items off: read-modify-write under one lock.
_lock = threading.Lock()


def _norm(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _id(source_id, text):
    return hashlib.sha1(f"{source_id}|{_norm(text)[:40]}".encode()).hexdigest()[:10]


class Reminders:
    def __init__(self, path):
        self.path = path

    def load(self):
        return read_json(self.path, [])

    def save(self, items):
        write_atomic(self.path, items)

    def open_items(self, items=None):
        """Not done, not snoozed, sorted by due date then priority."""
        today = date.today().isoformat()
        items = self.load() if items is None else items
        live = [r for r in items if not r.get("done_at") and (r.get("snoozed_until") or "") <= today]
        return sorted(live, key=lambda r: (r.get("due") or "9999", PRIORITY.get(r.get("priority"), 1)))

    def merge(self, found, sources):
        """Fold the briefing's reminders in. `sources` maps email/event ids to their links.
        An item naming an existing_id updates it; otherwise it's added unless it's a duplicate."""
        with _lock:
            items = self.load()
            by_id = {r["id"]: r for r in items}
            now = datetime.now(timezone.utc).isoformat()
            for f in found:
                existing = by_id.get(f.get("existing_id") or "")
                if existing:
                    if existing.get("done_at"):
                        continue  # the user closed it; don't resurrect it
                    existing.update(text=f["text"], due=f["due"], priority=f["priority"], updated=now)
                    continue
                rid = _id(f.get("source_id") or "", f["text"])
                if rid in by_id or any(_norm(r["text"]) == _norm(f["text"]) for r in items):
                    continue
                item = {
                    "id": rid, "text": f["text"], "due": f["due"], "priority": f["priority"],
                    "source": f["source"], "source_id": f.get("source_id"), "url": sources.get(f.get("source_id")),
                    "created": now, "done_at": None, "snoozed_until": None,
                }
                items.append(item)
                by_id[rid] = item
            # Forget finished items after 30 days so the file doesn't grow forever.
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            self.save([r for r in items if not r.get("done_at") or r["done_at"] > cutoff])

    def add(self, text, due=None, priority="medium"):
        with _lock:
            items = self.load()
            item = {
                "id": secrets.token_hex(5), "text": text, "due": due, "priority": priority, "source": "manual",
                "source_id": None, "url": None, "created": datetime.now(timezone.utc).isoformat(), "done_at": None, "snoozed_until": None,
            }
            items.append(item)
            self.save(items)
            return item

    def update(self, rid, **changes):
        with _lock:
            items = self.load()
            item = next((r for r in items if r["id"] == rid), None)
            if not item:
                raise KeyError(f"no reminder {rid}")
            item.update(changes)
            self.save(items)
            return item

    def done(self, rid):
        return self.update(rid, done_at=datetime.now(timezone.utc).isoformat())

    def snooze(self, rid, days=1):
        return self.update(rid, snoozed_until=(date.today() + timedelta(days=days)).isoformat())
