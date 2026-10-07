# TODO

## Model quality (local model)

- [ ] Check the Local tab's latest prompt fixes in a real run: events should get a real category (music, sports…)
      rather than all `venue`, titles should name the act, and summaries should be short highlights.
- [ ] The local model loosens length limits: meal "why" lines run well past ~80 characters, and briefing headlines
      are sometimes generic ("Daily Briefing"). Trim on the server, or retry once when a field is over its limit.
- [ ] Today's "Coming up" researches in-town events (home games). Skip events near home, or limit them to venue
      logistics.

## Scheduling and performance

- [ ] Every section shares one local model, so runs queue behind each other: at startup the Today briefing waited
      ~30 minutes behind Ski and three new trip tabs. Options: one LLM call at a time with priority (Today first),
      staggered `schedule_hours`, or skipping summaries at startup when the last one is recent.
- [ ] A server restart kills runs in progress. Finish or checkpoint the current run on SIGTERM.
- [ ] Ski sends ~40k tokens per request because search results pile up in the tool loop. Summarize or drop old tool
      results after each step.

## Trips

- [ ] A dismissed trip comes back if its dates move by more than 3 days. Match dismissed trips more loosely
      (same destination, overlapping dates).
- [ ] Trip tabs show the weather at the destination now. Show the forecast for the trip dates once they're within
      range (about 10–16 days).
- [ ] Show upcoming trips on the Today tab, with links to their tabs.

## Meals

- [ ] Overpass's public endpoint is rate-limited and sometimes slow. Cache results per venue, and fall back to
      another Overpass mirror.
- [ ] Check opening hours against the meal time on the server (parse `opening_hours`) instead of relying on the
      model.

## UI

- [ ] The Weather and Ski tabs still use the auto-fill grid, which leaves gaps beside short cards. Move them to the
      column layout that Today and Local use.
- [ ] The ⚙ model picker and the cost views assume Claude. With the local model, show tokens and time instead of
      dollars, and list the local server's models.
- [ ] `update_config` writes non-ASCII as `\u` escapes (emoji icons), so the file gets harder to read after page
      edits. Use `ensure_ascii=False`.

## Reliability and tests

- [ ] There are no tests. Start with `resolve_llm`, `_meals.meal_for`, trip matching in `_trips.detect`, and
      `strip_private`.
- [ ] Google API calls sometimes time out (seen once on a refresh). Retry once before falling back to the last data.
