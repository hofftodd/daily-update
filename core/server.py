"""The web server: the page, a small JSON API, the section scheduler, and the phone's location webhook.

Access: requests to http://localhost from this Mac need nothing. From anywhere else (phone over Tailscale or LAN)
open the page once as  http://<mac>:<port>/?token=<DASH_TOKEN from .env>  and a cookie keeps you signed in.

  GET  /api/sections                       tabs: every section's metadata and status
  GET  /api/sections/<id>                  one section's data and AI summary
  GET  /api/sections/<id>/prompts          exactly what was sent to the model last time, per call
  POST /api/sections/<id>/refresh          {"summary": true|false|null}  start a run now
  POST /api/sections/<id>/settings         {"key": ..., "value": ...}    change a cost lever
  POST /api/sections/<id>/actions/<name>   section-specific buttons (reminders, ...)
  POST /api/sections/<id>/remove           delete a dynamic (trip) tab; it won't be recreated
  GET  /api/usage                          AI cost totals and projections
  POST /api/location                       phone webhook, Authorization: Bearer <LOCATION_TOKEN>
"""

import hmac
import json
import mimetypes
import os
import re
import threading
from datetime import datetime, timezone
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from core import usage
from core.common import DATA, ROOT, km_between, load_config, load_env, log, read_json, update_config, write_atomic
from core.sections import Context, Runner, module_for, resolve_llm, section_cfg, section_cfgs, section_meta
from sections import _trips
from sections._research import interests

WEB = ROOT / "web"
MAX_BODY = 64 * 1024
COOKIE = "du_token"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
# Models llm.py can drive: adaptive thinking, effort and web_search_20260209 (Haiku 4.5 rejects all three).
MODELS = ("claude-sonnet-5-5", "claude-opus-5-5")


def _hours(v):
    return isinstance(v, list) and len(v) <= 24 and all(isinstance(h, int) and 0 <= h <= 23 for h in v)


# Only these can be changed from the page, and values are validated, so a click can't break config.json.
SETTINGS = {
    "llm.model": lambda v, c: v in MODELS,
    "llm.effort": lambda v, c: v in ("low", "medium", "high"),
    "llm.max_searches": lambda v, c: isinstance(v, int) and 0 <= v <= 20,
    "llm.profile": lambda v, c: v is None or v in c.get("providers", {}),
    "summary.schedule_hours": lambda v, c: _hours(v),
    "refresh_minutes": lambda v, c: isinstance(v, int) and 5 <= v <= 1440,
}


def strip_private(value):
    """Keys starting with "_" are for the server (e.g. full forecast discussions); the page never gets them."""
    if isinstance(value, dict):
        return {k: strip_private(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [strip_private(v) for v in value]
    return value


def runs_per_day(scfg):
    return len((scfg.get("summary") or {}).get("schedule_hours", []))


class Handler(BaseHTTPRequestHandler):
    server_version = "daily-update"
    runner: Runner = None  # set in main()

    # ------------------------------------------------------------ plumbing

    def _send(self, code, body, content_type="application/json", headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("body too large")
        if length and "application/json" not in (self.headers.get("Content-Type") or ""):
            raise ValueError("expected application/json")
        return json.loads(self.rfile.read(length) or b"{}") if length else {}

    def _token_ok(self, supplied):
        token = os.environ.get("DASH_TOKEN", "")
        return bool(token and supplied and hmac.compare_digest(supplied, token))

    def _authorized(self):
        # Plain localhost (checked on the Host header too, so a DNS-rebinding page can't borrow this exemption).
        host = self.headers.get("Host") or ""
        host = host.split("]")[0] + "]" if host.startswith("[") else host.rsplit(":", 1)[0]
        if self.client_address[0] in ("127.0.0.1", "::1") and host in LOCAL_HOSTS:
            return True
        jar = cookies.SimpleCookie(self.headers.get("Cookie") or "")
        if COOKIE in jar and self._token_ok(jar[COOKIE].value):
            return True
        auth = self.headers.get("Authorization") or ""
        return auth.startswith("Bearer ") and self._token_ok(auth[7:])

    def _same_origin(self):
        """Browsers send Origin on cross-site POSTs; without this check any web page open on this machine could
        post a form to localhost (which needs no token). The phone Shortcut sends no Origin."""
        origin = self.headers.get("Origin")
        return not origin or urlparse(origin).netloc == (self.headers.get("Host") or "")

    def log_message(self, fmt, *args):
        pass  # quiet; errors are logged where they happen

    # ------------------------------------------------------------ routes

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if "token" in query:  # sign in: set the cookie and drop the token from the address bar
            if not self._token_ok(query["token"][0]):
                return self._send(401, b"Wrong token.", "text/plain")
            cookie = f"{COOKIE}={query['token'][0]}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax"
            return self._send(302, b"", "text/plain", {"Location": url.path or "/", "Set-Cookie": cookie})
        if url.path == "/manifest.webmanifest" or url.path.startswith("/icon"):
            return self._static(url.path)  # the home-screen icon is fetched without cookies on iOS
        if not self._authorized():
            if url.path.startswith("/api/"):
                return self._send(401, {"error": "unauthorized"})
            return self._send(401, SIGN_IN_PAGE, "text/html; charset=utf-8")
        try:
            if url.path == "/api/sections":
                return self._sections()
            if url.path == "/api/usage":
                return self._usage()
            m = re.fullmatch(r"/api/sections/([\w-]+)(/prompts)?", url.path)
            if m:
                return self._prompts(m.group(1)) if m.group(2) else self._section(m.group(1))
            if url.path.startswith("/api/"):
                return self._send(404, {"error": "not found"})
            return self._static(url.path)
        except Exception as e:
            log(f"GET {url.path} failed: {e}")
            return self._send(500, {"error": str(e)})

    def do_POST(self):
        url = urlparse(self.path)
        if not self._same_origin():
            return self._send(403, {"error": "cross-site request"})
        if url.path == "/api/location":
            return self._location()
        if not self._authorized():
            return self._send(401, {"error": "unauthorized"})
        if url.path == "/api/interests":
            return self._interests()
        try:
            body = self._json_body()
        except (ValueError, json.JSONDecodeError) as e:
            return self._send(400, {"error": str(e)})
        m = re.fullmatch(r"/api/sections/([\w-]+)/(refresh|settings|remove|actions/(\w+))", url.path)
        if not m:
            return self._send(404, {"error": "not found"})
        sid, what, action = m.groups()
        config = load_config()
        scfg = section_cfg(config, sid)
        if not scfg:
            return self._send(404, {"error": f"no section {sid}"})
        try:
            if what == "refresh":
                summary = body.get("summary")
                started = self.runner.submit(sid, summary if summary in (True, False) else None)
                return self._send(202 if started else 409, {"started": started})
            if what == "settings":
                return self._settings(sid, body)
            if what == "remove":
                if not scfg.get("dynamic"):
                    return self._send(400, {"error": "only trip tabs can be removed"})
                _trips.dismiss(sid)
                log(f"[{sid}] tab removed")
                return self._send(200, {"ok": True})
            return self._action(config, scfg, action, body)
        except (KeyError, ValueError, TypeError) as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            log(f"POST {url.path} failed: {e}")
            return self._send(500, {"error": str(e)})

    # ------------------------------------------------------------ handlers

    def _sections(self):
        config = load_config()
        metas = []
        for s in section_cfgs(config):
            try:
                metas.append(section_meta(config, s, self.runner))
            except Exception as e:  # one broken section shouldn't take down the tab bar
                metas.append({"id": s["id"], "type": s.get("type"), "title": s.get("title", s["id"]), "icon": "⚠︎",
                              "errors": [f"Section failed to load: {e}"], "status": None})
        app = config.get("app", {})
        self._send(200, {
            "title": app.get("title", "Daily Update"),
            "units": config.get("units", "imperial"),
            "providers": sorted(config.get("providers", {})),
            "models": MODELS,
            "interests": interests(config),
            "sections": metas,
            "month_cost": usage.summary([])["month"],
        })

    def _section(self, sid):
        config = load_config()
        scfg = section_cfg(config, sid)
        if not scfg:
            return self._send(404, {"error": f"no section {sid}"})
        mod = module_for(scfg["type"])
        payload = self.runner.load_payload(sid) or {"id": sid, "type": scfg["type"], "data": None, "summary": None}
        if hasattr(mod, "present"):
            payload = mod.present(Context(config, scfg, payload, None), payload)
        llm = resolve_llm(config, scfg)
        payload = {**strip_private(payload), "meta": section_meta(config, scfg, self.runner),
                   "options": strip_private({k: v for k, v in scfg.items() if k not in ("llm", "privacy")}),
                   "privacy": scfg.get("privacy"), "llm_profile": (scfg.get("llm") or {}).get("profile"),
                   "provider": llm.get("provider")}
        self._send(200, payload)

    def _prompts(self, sid):
        if not section_cfg(load_config(), sid):
            return self._send(404, {"error": f"no section {sid}"})
        self._send(200, read_json(DATA / sid / "last_prompts.json", {}))

    def _usage(self):
        config = load_config()
        rows = [(s["id"], s.get("title", s["id"]), resolve_llm(config, s).get("model"), resolve_llm(config, s).get("provider"),
                 runs_per_day(s)) for s in section_cfgs(config) if hasattr(module_for(s["type"]), "summarize")]
        self._send(200, usage.summary(rows))

    def _settings(self, sid, body):
        key, value = body.get("key"), body.get("value")
        config = load_config()
        if key not in SETTINGS or not SETTINGS[key](value, config):
            return self._send(400, {"error": f"refusing {key}={value!r}"})

        def mutate(c):
            s = section_cfg(c, sid)
            *path, last = key.split(".")
            target = s
            for p in path:
                target = target.setdefault(p, {})
            if value is None:
                target.pop(last, None)
            else:
                target[last] = value

        update_config(mutate)
        log(f"[{sid}] setting {key} = {value!r}")
        self._send(200, {"ok": True})

    def _interests(self):
        """Replace the interests list (top level of config.json, shared by every section that researches)."""
        try:
            value = self._json_body().get("interests")
        except (ValueError, json.JSONDecodeError):
            value = None
        if not isinstance(value, list) or len(value) > 50 or not all(isinstance(i, str) and len(i) <= 200 for i in value):
            return self._send(400, {"error": "expected up to 50 interests, each under 200 characters"})
        value = [i.strip() for i in value if i.strip()]
        update_config(lambda c: c.__setitem__("interests", value))
        log(f"interests set: {len(value)} items")
        self._send(200, {"ok": True, "interests": value})

    def _action(self, config, scfg, action, body):
        mod = module_for(scfg["type"])
        fn = getattr(mod, "ACTIONS", {}).get(action)
        if not fn:
            return self._send(404, {"error": f"no action {action}"})
        ctx = Context(config, scfg, self.runner.load_payload(scfg["id"]), None)
        result = fn(ctx, body) or {}
        if result.pop("run", False):
            result["started"] = self.runner.submit(scfg["id"], None)
        self._send(200, result)

    def _location(self):
        token = os.environ.get("LOCATION_TOKEN", "")
        auth = self.headers.get("Authorization", "")
        if not token or not hmac.compare_digest(auth, f"Bearer {token}"):
            return self._send(401, {"error": "unauthorized"})
        try:
            body = self._json_body()
            lat, lon = float(body["lat"]), float(body["lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("out of range")
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            return self._send(400, {"error": f"expected JSON with lat and lon ({e})"})
        from sources.location import PHONE_PATH

        fix = {"lat": lat, "lon": lon, "accuracy_m": body.get("accuracy_m"), "time": datetime.now(timezone.utc).isoformat()}
        write_atomic(PHONE_PATH, fix)
        log(f"phone location {lat:.4f},{lon:.4f}")
        # A big move refreshes the sections that follow you now, rather than at their next scheduled run: Local
        # re-researches (its summary_due compares against where research last ran), Today updates place and weather.
        for s in section_cfgs(load_config()):
            if s["type"] not in ("daily", "local") or s.get("place"):
                continue
            payload = self.runner.load_payload(s["id"]) or {}
            if s["type"] == "local":
                last = (payload.get("summary") or {}).get("location")
            else:
                last = (payload.get("data") or {}).get("location")
            trigger = (s.get("research") or {}).get("trigger_km", 40)
            if not last or last.get("lat") is None or km_between(fix, last) >= trigger:
                self.runner.submit(s["id"], None)
        self._send(200, {"ok": True})

    def _static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (WEB / rel).resolve()
        if WEB.resolve() not in target.parents or not target.is_file():
            return self._send(404, b"Not found", "text/plain")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            ctype = "text/javascript"
        elif target.suffix == ".webmanifest":
            ctype = "application/manifest+json"
        if ctype.startswith("text/") or ctype.endswith(("json", "javascript", "svg+xml")):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)


SIGN_IN_PAGE = b"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>Daily Update</title><style>body{font:16px -apple-system,system-ui,sans-serif;max-width:28rem;margin:15vh auto;padding:0 16px;color:#222}
@media(prefers-color-scheme:dark){body{background:#151514;color:#eee}}input,button{font:inherit;padding:.6em .8em;border-radius:10px;border:1px solid #8886}
form{display:flex;gap:8px;margin-top:1em}input{flex:1;min-width:0}</style>
<h2>Daily Update</h2><p>Enter the access token (DASH_TOKEN in the project's .env). You'll stay signed in on this device.</p>
<form method=get action="/"><input name=token type=password autocomplete=current-password placeholder="Token" autofocus><button>Sign in</button></form>"""


def main():
    load_env()
    if not os.environ.get("DASH_TOKEN"):
        raise SystemExit("Set DASH_TOKEN in .env first (install.sh generates one).")
    config = load_config()
    sc = config.get("server", {})
    host, port = os.environ.get("HOST", sc.get("host", "0.0.0.0")), int(os.environ.get("PORT", sc.get("port", 8770)))

    runner = Runner(workers=sc.get("workers", 3))
    Handler.runner = runner
    stop = threading.Event()
    threading.Thread(target=runner.loop, args=(stop,), daemon=True, name="scheduler").start()

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    log(f"serving on http://{host}:{port} (sections: {', '.join(s['id'] for s in section_cfgs(config))})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()


if __name__ == "__main__":
    main()
