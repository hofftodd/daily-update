#!/usr/bin/env python3
"""Read-only Gmail and Google Calendar access.

One-time setup: put your OAuth client file at ./credentials.json (see README), then run
  .venv/bin/python -m sources.google auth
which opens a browser for consent and stores the refresh token in data/google/token.json.
"""

import base64
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from core.common import DATA, ROOT, log

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]
CLIENT_FILE = ROOT / "credentials.json"
TOKEN_FILE = DATA / "google" / "token.json"


class NotAuthorized(RuntimeError):
    pass


def credentials(interactive=False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES) if TOKEN_FILE.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds)
            return creds
        except Exception as e:
            log(f"Google token refresh failed: {e}")
    if not interactive:
        raise NotAuthorized("Google not connected: run `.venv/bin/python -m sources.google auth`")
    if not CLIENT_FILE.exists():
        raise SystemExit(f"Missing {CLIENT_FILE}. Create a Desktop OAuth client in Google Cloud Console (see README).")
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or sys.platform == "darwin":
        creds = flow.run_local_server(port=0)
    else:
        creds = _headless_auth(flow)
    _save(creds)
    return creds


PENDING_FILE = DATA / "google" / "pending.json"
REDIRECT = "http://localhost"  # the Desktop client's registered redirect; nothing needs to listen there


def _headless_auth(flow):
    """No browser here (e.g. over SSH): consent in any browser, then paste back the localhost URL it lands on.
    The flow's PKCE verifier is saved so `auth <address>` can finish in a separate run (no prompt needed)."""
    flow.redirect_uri = REDIRECT
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps({"state": state, "code_verifier": flow.code_verifier}))
    os.chmod(PENDING_FILE, 0o600)
    print(f"Open this in a browser and approve access:\n\n  {url}\n")
    print("The browser then fails to load a http://localhost/?state=...&code=... page. That's expected.")
    if not sys.stdin.isatty():
        print("Then run:  .venv/bin/python -m sources.google auth '<that page's full address>'")
        raise SystemExit(0)
    return _finish_auth(flow, input("Paste that page's full address here: "))


def _finish_auth(flow, reply):
    from urllib.parse import parse_qs, urlparse

    pending = json.loads(PENDING_FILE.read_text()) if PENDING_FILE.exists() else None
    if not pending:
        raise SystemExit("No sign-in in progress: run `.venv/bin/python -m sources.google auth` first.")
    query = parse_qs(urlparse(reply.strip()).query)
    if "code" not in query:
        raise SystemExit(f"No authorization code in that address: {query.get('error', ['?'])[0]}")
    if query.get("state", [None])[0] != pending["state"]:
        raise SystemExit("That address is from an older sign-in link: run `auth` again and use the new link.")
    flow.redirect_uri = REDIRECT
    flow.code_verifier = pending["code_verifier"]
    flow.fetch_token(code=query["code"][0])
    PENDING_FILE.unlink()
    return flow.credentials


def finish_auth(reply):
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = _finish_auth(InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES), reply)
    _save(creds)
    return creds


def _save(creds):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json())
    os.chmod(TOKEN_FILE, 0o600)


def _service(name, version):
    from googleapiclient.discovery import build

    return build(name, version, credentials=credentials(), cache_discovery=False)


# ---------------------------------------------------------------- Gmail


def _decode(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _body_text(payload):
    """Prefer text/plain; fall back to stripped text/html."""
    plain, rich = [], []

    def walk(part):
        mime, data = part.get("mimeType", ""), (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            rich.append(_decode(data))
        for p in part.get("parts") or []:
            walk(p)

    walk(payload)
    if plain:
        text = "\n".join(plain)
    else:
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", "\n".join(rich))
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"(?m)^>.*$", "", text)  # drop quoted reply history
    return re.sub(r"\s+", " ", text).strip()


def fetch_emails(lookback_hours=36, max_emails=40, body_chars=1200):
    """Recent inbox mail, minus promotions/social/forums. Bodies are trimmed: this goes to a local model."""
    gmail = _service("gmail", "v1")
    days = max(1, -(-lookback_hours // 24))
    query = f"in:inbox newer_than:{days}d -category:promotions -category:social -category:forums"
    ids = gmail.users().messages().list(userId="me", q=query, maxResults=max_emails).execute().get("messages", [])
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    emails = []
    for m in ids:
        msg = gmail.users().messages().get(userId="me", id=m["id"], format="full").execute()
        received = datetime.fromtimestamp(int(msg["internalDate"]) / 1000, timezone.utc)
        if received < cutoff:
            continue
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        labels = msg.get("labelIds", [])
        emails.append({
            "id": msg["id"],
            "thread_id": msg["threadId"],
            "from": headers.get("from", ""),
            "subject": headers.get("subject", "(no subject)"),
            "received": received.astimezone().isoformat(timespec="minutes"),
            "unread": "UNREAD" in labels,
            "important": "IMPORTANT" in labels,
            "starred": "STARRED" in labels,
            "body": _body_text(msg["payload"])[:body_chars],
            "url": f"https://mail.google.com/mail/u/0/#inbox/{msg['threadId']}",
        })
    return emails


# ---------------------------------------------------------------- Calendar


def fetch_events(days=7):
    cal = _service("calendar", "v3")
    start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days + 1)
    calendars = [c for c in cal.calendarList().list().execute().get("items", []) if c.get("selected", True)]
    events = []
    for c in calendars:
        try:
            items = cal.events().list(
                calendarId=c["id"], timeMin=start.isoformat(), timeMax=end.isoformat(),
                singleEvents=True, orderBy="startTime", maxResults=100,
            ).execute().get("items", [])
        except Exception as e:
            log(f"calendar {c.get('summary')} failed: {e}")
            continue
        for e in items:
            if e.get("status") == "cancelled":
                continue
            me = next((a for a in e.get("attendees", []) if a.get("self")), None)
            if me and me.get("responseStatus") == "declined":
                continue
            s, en = e.get("start", {}), e.get("end", {})
            events.append({
                "id": e["id"],
                "calendar": c.get("summaryOverride") or c.get("summary"),
                "title": e.get("summary", "(busy)"),
                "start": s.get("dateTime") or s.get("date"),
                "end": en.get("dateTime") or en.get("date"),
                "all_day": "date" in s,
                "location": e.get("location"),
                "description": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", e.get("description") or ""))).strip()[:400],
                "video": e.get("hangoutLink"),
                "response": me.get("responseStatus") if me else None,
                "url": e.get("htmlLink"),
            })
    return sorted(events, key=lambda e: e["start"])


if __name__ == "__main__":
    if sys.argv[1:] == ["auth"]:
        credentials(interactive=True)
        print(f"Connected. Token saved to {TOKEN_FILE}")
    elif sys.argv[1:2] == ["auth"] and len(sys.argv) == 3:
        finish_auth(sys.argv[2])
        print(f"Connected. Token saved to {TOKEN_FILE}")
    elif sys.argv[1:] == ["test"]:
        ev, em = fetch_events(2), fetch_emails(24, 10)
        print(f"{len(ev)} events in the next 2 days, {len(em)} emails in the last 24h")
        for e in ev[:5]:
            print(f"  {e['start']}  {e['title']}")
        for m in em[:5]:
            print(f"  {m['from'][:30]:30}  {m['subject'][:60]}")
    else:
        print(__doc__)
