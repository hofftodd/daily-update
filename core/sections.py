"""Sections: the plugin contract, and the runner that schedules and executes them.

A section type is a module in sections/ (sections/weather.py -> type "weather") with:

  TITLE, ICON                   defaults for the tab
  gather(ctx) -> dict           fetch data; no AI, so it's free and runs every `refresh_minutes`
  summarize(ctx, data) -> dict  optional: the AI summary, run at the `summary.schedule_hours` slots or on demand
  summary_due(ctx) -> bool      optional: extra reasons to summarize off-schedule
  present(ctx, payload) -> payload   optional: merge live state (e.g. reminders) into what the page gets
  ACTIONS = {name: fn(ctx, body) -> dict}   optional: buttons on the page (check off a reminder, ...)

and a renderer in web/sections/<type>.js. Each section instance in config.json gets its own data/<id>/ folder,
so the same type can appear twice (say, two weather tabs for different places).
"""

import importlib
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from core import usage
from core.common import DATA, load_config, log, read_json, slot_passed, write_atomic
from core.llm import generate

RETRY_AFTER = timedelta(minutes=30)


def module_for(section_type):
    return importlib.import_module(f"sections.{section_type}")


def section_cfgs(config, enabled_only=True):
    return [s for s in config.get("sections", []) if s.get("enabled", True) or not enabled_only]


def section_cfg(config, sid):
    return next((s for s in config.get("sections", []) if s["id"] == sid), None)


def resolve_llm(config, scfg):
    """App-wide llm settings, then a named provider profile if one is picked, then the section's own overrides."""
    base = dict(config.get("llm", {}))
    over = dict(scfg.get("llm") or {})
    profile = over.pop("profile", None) or base.pop("profile", None)
    if profile:
        base.update(config.get("providers", {}).get(profile, {}))
    base.update(over)
    base.setdefault("provider", "anthropic")
    return base


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class Context:
    """What a section gets to work with during a run."""

    def __init__(self, config, scfg, prev, runner, forced=False):
        self.config = config
        self.cfg = scfg
        self.id = scfg["id"]
        self.prev = prev or {}
        self.units = config.get("units", "imperial")
        self.dir = DATA / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.errors = []
        self.forced = forced
        self.scratch = {}  # handed from gather() to summarize() within one run; never written to disk
        self._runner = runner

    def status(self, text):
        if self._runner:
            self._runner.set_status(self.id, text)
        if text:
            log(f"[{self.id}] {text}")

    def error(self, msg):
        self.errors.append(msg)
        log(f"[{self.id}] {msg}")

    def place(self, place_id):
        return next((p for p in self.config.get("places", []) if p["id"] == place_id), None)

    @property
    def llm_cfg(self):
        return resolve_llm(self.config, self.cfg)

    def llm(self, *, call, system, user, schema, description="Publish the finished result.", web_searches=None):
        cfg = self.llm_cfg
        searches = cfg.get("max_searches", 0) if web_searches is None else web_searches
        # Models don't know the date, and without it web searches drift to past seasons.
        system = f"{system}\n\nToday is {datetime.now().astimezone():%A, %B %-d, %Y}."
        # Keep exactly what was sent, so the page can show it ("what gets sent").
        prompts = read_json(self.dir / "last_prompts.json", {})
        prompts[call] = {"time": now_iso(), "provider": cfg["provider"], "model": cfg.get("model"),
                         "web_searches": searches, "system": system, "user": user}
        write_atomic(self.dir / "last_prompts.json", prompts)
        return generate(
            cfg, system=system, user=user, schema=schema, name=call, description=description, web_searches=searches,
            on_usage=lambda u, ok: usage.record(self.id, call, u, ok, cfg["provider"]),
        )


class Runner:
    """Runs sections in a small thread pool: one run per section at a time, a few sections in parallel."""

    def __init__(self, workers=3):
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="section")
        self.lock = threading.Lock()
        self.running = {}  # section id -> {"text", "started", "summary"}

    # ------------------------------------------------------------ state

    @staticmethod
    def payload_path(sid):
        return DATA / sid / "payload.json"

    def load_payload(self, sid):
        return read_json(self.payload_path(sid))

    def set_status(self, sid, text):
        with self.lock:
            if sid in self.running:
                self.running[sid]["text"] = text

    def status(self, sid):
        with self.lock:
            return dict(self.running[sid]) if sid in self.running else None

    # ------------------------------------------------------------ running

    def submit(self, sid, summary=None):
        """summary: True forces an AI summary, False skips it, None follows the schedule.
        Returns False if the section is already running."""
        with self.lock:
            if sid in self.running:
                return False
            self.running[sid] = {"text": "Starting…", "started": now_iso(), "summary": summary}
        self.pool.submit(self._run, sid, summary)
        return True

    def _run(self, sid, summary):
        try:
            self._run_inner(sid, summary)
        except Exception as e:
            log(f"[{sid}] run crashed: {e}\n{traceback.format_exc()}")
        finally:
            with self.lock:
                self.running.pop(sid, None)

    def _run_inner(self, sid, summary):
        config = load_config()
        scfg = section_cfg(config, sid)
        if not scfg:
            return
        mod = module_for(scfg["type"])
        prev = self.load_payload(sid) or {}
        ctx = Context(config, scfg, prev, self, forced=summary is True)

        ctx.status("Fetching data…")
        try:
            data = mod.gather(ctx)
            generated_at = now_iso()
        except Exception as e:
            ctx.error(f"Data refresh failed: {e}")
            log(traceback.format_exc())
            data, generated_at = prev.get("data"), prev.get("generated_at")

        result, summary_at = prev.get("summary"), prev.get("summary_generated_at")
        attempted_at = prev.get("summary_attempted_at")
        if hasattr(mod, "summarize") and data is not None and summary is not False:
            if summary is True or self.summary_due(mod, ctx):
                ctx.status("Writing the AI summary…")
                attempted_at = now_iso()
                try:
                    result = mod.summarize(ctx, data)
                    summary_at = now_iso()
                except Exception as e:
                    ctx.error(f"AI summary failed: {e}")
                    log(traceback.format_exc())

        write_atomic(self.payload_path(sid), {
            "id": sid,
            "type": scfg["type"],
            "generated_at": generated_at,
            "summary_generated_at": summary_at,
            "summary_attempted_at": attempted_at,
            "data": data,
            "summary": result,
            "errors": ctx.errors,
        })
        log(f"[{sid}] done ({len(ctx.errors)} errors)")

    @staticmethod
    def backing_off(prev):
        """After a failed AI summary, wait before trying again rather than retrying every tick."""
        attempted, done = prev.get("summary_attempted_at"), prev.get("summary_generated_at")
        if not attempted or (done and done >= attempted):
            return False
        return datetime.now(timezone.utc) - datetime.fromisoformat(attempted) < RETRY_AFTER

    @classmethod
    def summary_due(cls, mod, ctx):
        if cls.backing_off(ctx.prev):
            return False
        hours = (ctx.cfg.get("summary") or {}).get("schedule_hours", [])
        if slot_passed(ctx.prev.get("summary_generated_at"), hours):
            return True
        return bool(getattr(mod, "summary_due", None) and mod.summary_due(ctx))

    # ------------------------------------------------------------ schedule

    def tick(self):
        """Start any section whose data is stale or whose AI summary slot has passed."""
        try:
            config = load_config()
        except Exception as e:
            log(f"config.json unreadable, skipping this tick: {e}")
            return
        for scfg in section_cfgs(config):
            sid = scfg["id"]
            if self.status(sid):
                continue
            prev = self.load_payload(sid) or {}
            stamp = prev.get("generated_at")
            refresh = timedelta(minutes=scfg.get("refresh_minutes", 30))
            data_due = not stamp or datetime.now(timezone.utc) - datetime.fromisoformat(stamp) >= refresh
            hours = (scfg.get("summary") or {}).get("schedule_hours", [])
            summary_due = slot_passed(prev.get("summary_generated_at"), hours) and not self.backing_off(prev)
            if data_due or summary_due:
                self.submit(sid, None)

    def loop(self, stop, every_s=30):
        while not stop.is_set():
            self.tick()
            stop.wait(every_s)


def section_meta(config, scfg, runner):
    """What the tab bar and footer need about a section, without its (possibly large) data."""
    sid = scfg["id"]
    mod = module_for(scfg["type"])
    payload = runner.load_payload(sid) or {}
    llm = resolve_llm(config, scfg)
    summary = scfg.get("summary") or {}
    return {
        "id": sid,
        "type": scfg["type"],
        "title": scfg.get("title") or getattr(mod, "TITLE", sid),
        "icon": scfg.get("icon") or getattr(mod, "ICON", "•"),
        "has_summary": hasattr(mod, "summarize"),
        "uses_interests": getattr(mod, "USES_INTERESTS", False),
        "dynamic": bool(scfg.get("dynamic")),
        "refresh_minutes": scfg.get("refresh_minutes", 30),
        "schedule_hours": summary.get("schedule_hours", []),
        "llm": {k: llm.get(k) for k in ("provider", "model", "effort", "max_searches")},
        "generated_at": payload.get("generated_at"),
        "summary_generated_at": payload.get("summary_generated_at"),
        "errors": payload.get("errors", []),
        "status": runner.status(sid),
    }
