# Daily Update

A locally served web page of AI-written summaries, one tab per topic. It works on a desktop browser and on your
phone.

| Tab | Type | What it does |
|---|---|---|
| ☀️ Today | `daily` | Location, weather, calendar, email that needs you, reminders, and research on upcoming calendar events |
| 📍 Local | `local` | Events in the next two weeks and what's worth knowing where you are now, researched around your interests |
| ✈️ *Trip* | `local` | Added automatically for travel found on your calendar: the same research, for the destination and dates |
| 🌤️ Weather | `weather` | Home and cabin conditions, local stations, SNOTEL, the week ahead, and a forecaster-style summary |
| 🎿 Ski | `ski` | Regional snow outlook, home mountain, avalanche forecast, other mountains, with resort status checked by web search |

All AI work runs on a local model by default (any OpenAI-compatible server: llama.cpp, llama-swap, LM Studio,
Ollama), so nothing is sent to a cloud model and summaries cost nothing. Any section can be switched to Claude
instead (see [Models](#models)).

Every section works the same way:

1. **Gather:** fetch data (free, no AI) every `refresh_minutes`.
2. **Summarize:** have a model write a structured summary at the `summary.schedule_hours` slots, or when you tap **✦ New AI summary**.
3. **Render:** draw the result in the browser.

## Setup

```sh
./install.sh     # venv, config.json, access tokens in .env, and a service that keeps the server running:
                 # a launchd agent on macOS, a systemd user service on Linux
```

Then:

1. **Config:** `install.sh` copies `config.example.json` to `config.json` if there isn't one. `config.json` is
   git-ignored because it holds your places and interests, and the app edits it (⚙ settings, trip tabs). Set your
   `places` (home, cabin, mountains), `interests`, and `providers.local` (your OpenAI-compatible model server).
2. **Model:** with the default local model, there's nothing more to do. To use Claude for any section, add
   `ANTHROPIC_API_KEY=...` to `.env`.
3. **Google** (optional, for Today's email and calendar). Gmail and Calendar are requested read-only:
   1. In the [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the **Gmail API**
      and the **Google Calendar API**.
   2. Under **APIs & Services → OAuth consent screen**, choose **External**, and add your own Google account under
      **Test users**. (Keeping the app in testing mode is fine; it stays private to you.)
   3. Under **Credentials**, create an **OAuth client ID** of type **Desktop app** and download its JSON to
      `credentials.json` in the project root. It's git-ignored.
   4. Run `.venv/bin/python -m sources.google auth`. On a desktop it opens a browser for consent. Over SSH it prints
      a URL instead: open it anywhere, approve, then run `.venv/bin/python -m sources.google auth "<the
      localhost address it lands on>"` to finish. The refresh token is written to `data/google/token.json`
      (mode 600, git-ignored).

   Skip this and Today still works: it just omits the email and calendar parts.
4. **Desktop:** open http://localhost:8770.
5. **Phone** (optional, Tailscale or LAN): the server listens on `127.0.0.1` by default. To reach it from your phone,
   set `server.host` to `0.0.0.0` in `config.json` and restart. Prefer a private network (Tailscale) over an
   untrusted LAN — the page summarizes your email. Then open
   `http://<host-name>:8770/?token=<DASH_TOKEN from .env>` once; a cookie keeps you signed in. In Safari,
   **Share → Add to Home Screen** makes it open like an app.
6. **Phone location** (optional): have an iOS Shortcut POST `{"lat": …, "lon": …}` to
   `http://<host>:8770/api/location` with the header `Authorization: Bearer <LOCATION_TOKEN from .env>`. Without it,
   location falls back to the last known fix, then to your `home` place.

Logs are in `data/server.log`. To run it in the foreground while developing, use `.venv/bin/python -m core.server`.
Stop the server with `launchctl bootout gui/$(id -u)/com.daily-update.server` (macOS) or
`systemctl --user stop daily-update` (Linux; `restart` after pulling changes). On Linux, run
`sudo loginctl enable-linger $USER` once so the service starts at boot without a login. Location there comes from
the phone (or home): Mac location needs CoreLocationCLI.

## Using it

- Tabs are along the top on desktop and at the bottom on a phone. Keys `1`–`9` switch tabs.
- **↻ Refresh** fetches fresh data (free). **✦ New AI summary** writes a new summary now.
- **⚙** sets the model, effort, web-search cap, summary times and refresh interval for that tab. It also shows the
  monthly cost estimate and **What gets sent**: the exact prompts from the last run.
- **$** shows AI spend: today, this week, this month, a 14-day chart, and a projection per section.

## Interests

`config.json` → `interests` is one list shared by every section. Research on the Local tab and on Today's calendar
events is aimed at it. Edit the list in the file; the next research run picks it up.

## Local tab

Local research runs at its summary times, and also as soon as you've moved `research.trigger_km` (40) from where it
last ran. **🔎 Explore** runs it again now. It makes two web-search calls: dated events within `horizon_days` (14),
and a "good to know" pass for news, openings, conditions and tips. Neither call sees email or calendar.

## Meals around events

For events today and tomorrow that fall near a mealtime, the Agenda suggests places to eat close to the venue, e.g.
"🍽 Dinner after: …". A mealtime here means within 90 minutes of breakfast (7–9:30), lunch (11:30–1:30) or dinner
(5–8). Candidates are real places from OpenStreetMap near the geocoded venue. The model picks from that list, with a
few web searches to check reviews and hours, so it can't invent a restaurant. It skips all-day events, events
without a location, events at home, and events that are already meals. Settings are under `meals` in the daily
section (`days`, `per_run`, `max_searches`, `picks`). Picks are reused until the event's time or place changes.

## Trip tabs

During its AI runs, Today checks the next `trips.lookahead_days` (45) of your calendar for travel: flights, lodging,
and events in another city. Each destination at least `trips.min_km` (100) from home gets its own ✈️ tab after Local.
That tab is a Local tab pinned to the destination and limited to the trip's dates. Trip state is in
`data/trips.json`, and trip tabs are entries in `config.json` with `"dynamic": true`.

- **✕** in a trip tab's header removes it, and that trip won't be added again.
- A trip tab removes itself the day after the trip ends.
- Turn detection off with `"trips": {"enabled": false}` in the daily section.

Trip detection sees only the title, time and location of events you've accepted. Calendar is checked again only
when it changes.

## Privacy (Today tab)

Email and calendar go to the model that section uses: your local model as configured, or Claude if you switch the
tab to Anthropic in ⚙. The `privacy` block in `config.json` controls what's sent:

| Key | Default | |
|---|---|---|
| `email_lookback_hours`, `max_emails` | 36, 25 | Inbox only. Promotions, social and forums are always skipped |
| `email_body_chars` | 600 | Body sent for unread, important or starred mail. `0` sends sender and subject only |
| `email_snippet_chars` | 120 | Body sent for everything else |
| `drop_sensitive_emails` | true | Never sends one-time codes, password resets or sign-in alerts |
| `redact_email_addresses` | false | Sends "Jane Doe" instead of "Jane Doe <jane@…>" |
| `exclude_senders` | [] | Substrings of the From header, e.g. `"@mybank.com"` |
| `exclude_calendars` | [] | Calendar names that are never read |
| `include_event_descriptions` | true | Event descriptions, trimmed to 400 characters |

Prompt-injection boundaries:

- The briefing call reads email but has no tools.
- The research calls can search the web but never see email. For events, they see only the title, time and
  location of events you've accepted.

With the local model, email and calendar never leave your network. Web research still sends search queries to
DuckDuckGo and fetches pages, but no email content.

## Adding a section

1. Add `sections/<type>.py`:

   ```python
   TITLE, ICON = "Tides", "🌊"

   def gather(ctx):                 # free data fetch; return anything JSON-able
       return {"stations": [...]}

   def summarize(ctx, data):        # optional AI summary
       result, info = ctx.llm(call="tides", system=SYSTEM, user=prompt, schema=SCHEMA)
       return result

   ACTIONS = {"name": lambda ctx, body: {...}}   # optional buttons (data-action="name" in the page)
   ```

   `ctx` gives you:

   - `ctx.cfg`: this section's config entry
   - `ctx.config`: the whole config
   - `ctx.place(id)`: a place from the shared `places` list
   - `ctx.prev`: the last payload
   - `ctx.dir`: the section's own folder under `data/`
   - `ctx.status(text)`, `ctx.error(text)`
   - `ctx.llm(...)`: a structured-output model call with optional web search. It's logged for cost and for
     "What gets sent"

   Keys in your data that start with `_` stay on the server and are never sent to the page.
2. Add `web/sections/<type>.js` exporting `render(payload)`, where `payload` has `data`, `summary`, `generated_at` and
   `summary_generated_at`. Build markup with the `html` tag from `web/lib.js`. It escapes everything you
   interpolate, so text from email or the web can't inject markup.
3. Add an entry to `config.json` → `sections`: `id`, `type`, `title`, `icon`, `refresh_minutes`,
   `summary.schedule_hours`, optional `llm` overrides, and the section's own options. Order in the file is tab order.
   The same type can appear more than once with different options.

## Models

`config.json` → `llm` is the default for every section, and each section's `llm` overrides it:

- **Local** (what every section uses now): `"llm": {"profile": "local"}` uses `providers.local`, which is any
  OpenAI-compatible server (llama.cpp, llama-swap, LM Studio, Ollama). It needs `json_schema` response format and
  tool calling. Web search runs locally through DuckDuckGo plus a page reader, and `max_steps` caps the tool loop
  (the Local tab uses 24). Thinking models are fine: `<think>` blocks are stripped.
- **Anthropic:** remove the section's `profile` (or pick "Claude" in ⚙) to use `llm.model`, `effort` and
  `max_searches`. Web search uses Anthropic's server-side tool. Needs `ANTHROPIC_API_KEY` in `.env`.

Every call is told today's date, so web searches don't drift to past seasons.

## Layout

```
core/      server.py (HTTP + auth + scheduler), sections.py (plugin contract + runner), llm.py (providers),
           usage.py (cost log), common.py
sources/   data fetchers: weather (Open-Meteo, NWS, stations, SNOTEL), snow (avalanche, snow-forecast.com,
           YouTube), google (Gmail/Calendar, read-only), location (Mac + phone, geocoding), places (OpenStreetMap
           restaurants)
sections/  one module per section type (daily, local, weather, ski), plus shared helpers: _here (current location),
           _research (interest-aware web research), _trips (trip tabs), _meals (restaurants near events),
           _places, _reminders
web/       index.html, app.css, app.js (shell), lib.js (helpers), sections/<type>.js (renderers)
data/      per-section payloads, prompts, reminders, research, trips.json, usage.jsonl, logs (git-ignored)
config.example.json   the starting config; your config.json is git-ignored
TODO.md    known issues and ideas
```
