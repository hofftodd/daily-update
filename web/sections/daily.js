// Daily Update: now & weather, the briefing, reminders, agenda, email that needs you, and research on calendar events.
// Buttons use data-action="<name>" (posted to the section's ACTIONS); forms with data-action post their fields.

import { addDays, ago, card, chip, dayLabel, empty, finding, html, link, localDate, navLink, r0, raw, safeUrl, timeOf, wmo } from "../lib.js";

const SOURCE_ICON = { mac: "💻", phone: "📱" };
const eventDate = (e) => (e.all_day ? e.start : localDate(new Date(e.start)));
const senderName = (from) => (from || "").replace(/<.*>/, "").replace(/"/g, "").trim() || from;
// Next 12 hours: temperature line over precipitation-chance bars.
const hourStrip = (hourly) => {
  const hrs = (hourly || []).slice(0, 12);
  if (hrs.length < 2) return "";
  const W = 360, H = 34, slot = W / hrs.length;
  const temps = hrs.map((h) => h.temperature_2m);
  const lo = Math.min(...temps), hi = Math.max(...temps);
  const y = (t) => 4 + (1 - (t - lo) / Math.max(1, hi - lo)) * (H - 14);
  const line = hrs.map((h, i) => `${i ? "L" : "M"}${(i * slot + slot / 2).toFixed(1)},${y(h.temperature_2m).toFixed(1)}`).join(" ");
  const bars = hrs.map((h, i) => {
    const p = h.precipitation_probability || 0;
    const bh = (p / 100) * (H - 4);
    return `<g><title>${timeOf(h.time)}: ${r0(h.temperature_2m)}°, ${p}% precip</title><rect x="${i * slot}" y="0" width="${slot}" height="${H + 12}" fill="transparent"/>` +
      (bh > 1 ? `<rect class="pbar" x="${i * slot + slot / 2 - 5}" y="${H - bh}" width="10" height="${bh}" rx="2" style="opacity:${(0.25 + p / 160).toFixed(2)}"/>` : "") +
      (i % 3 === 0 ? `<text class="axis" x="${i * slot + slot / 2}" y="${H + 10}" text-anchor="middle">${i === 0 ? "now" : timeOf(h.time)}</text>` : "") + "</g>";
  });
  return raw(`<svg class="hourstrip" viewBox="0 0 ${W} ${H + 12}" role="img" aria-label="Next 12 hours">${bars.join("")}<path class="tline" d="${line}"/><text class="tlabel" x="2" y="${y(temps[0]) - 3}">${r0(temps[0])}°</text></svg>`);
};

const nowCard = (data, b) => {
  const w = data.weather;
  const loc = data.location || {};
  const cur = (w && w.current) || {};
  const today = (w && w.daily && w.daily[0]) || {};
  const [icon, label] = wmo(cur.weather_code, cur.is_day);
  return card({
    title: html`<span title="From ${loc.source} · ${ago(loc.time)}">${SOURCE_ICON[loc.source] || "🏠"} ${loc.label}</span>`,
    right: new Date().toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" }),
    body: w ? html`
      <div class="now">
        <div class="now-icon" title="${label}">${icon}</div>
        <div class="now-temp">${r0(cur.temperature_2m)}°</div>
        <div class="now-facts">
          <span>${label}</span>
          <span>H ${r0(today.temperature_2m_max)}° · L ${r0(today.temperature_2m_min)}°</span>
          <span>Feels ${r0(cur.apparent_temperature)}° · 💨 ${r0(cur.wind_speed_10m)} mph</span>
          <span>💧 ${r0(today.precipitation_probability_max)}% · UV ${r0(today.uv_index_max)}</span>
        </div>
      </div>
      ${hourStrip(w.hourly)}
      ${b && b.weather_note ? html`<p class="note">${b.weather_note}</p>` : ""}` : empty("Weather unavailable."),
  });
};

// Where you are now, from the freshest Mac or phone fix (refreshed with the data, not the AI run).
const SOURCE_NAME = { mac: "this Mac", phone: "your phone", trip: "trip" };
const whereLine = (loc) =>
  loc && loc.label
    ? html`<div class="where">📍 <b>${loc.label}</b> <span class="tiny">· ${SOURCE_NAME[loc.source] ? `from ${SOURCE_NAME[loc.source]} ${ago(loc.time)}` : "home (no recent location fix)"}</span></div>`
    : "";

const briefingCard = (b, at, loc) =>
  card({
    title: html`Briefing ${whereLine(loc)}`,
    right: b ? `AI · ${ago(at)}` : "",
    cls: "hero",
    body: b
      ? html`<div class="headline">${b.headline}</div><p class="lede">${b.summary}</p>`
      : empty("Your first briefing appears after the next scheduled run, or tap ✦ New AI summary."),
  });

const dueChip = (due) => {
  if (!due) return "";
  const today = localDate();
  if (due < today) return chip("overdue", "critical");
  if (due === today) return chip("today", "warning");
  return chip(due === addDays(1) ? "tomorrow" : dayLabel(due));
};

const remindersCard = (items) => {
  const list = (items || []).slice(0, 10);
  return card({
    title: "Remember",
    right: list.length ? `${list.length} open` : "all clear",
    body: html`
      <ul class="reminders">${list.map((r) => html`
        <li class="${r.priority === "high" ? "high" : ""}">
          <button class="check" data-action="reminder_done" data-id="${r.id}" title="Done" aria-label="Mark done"></button>
          <span class="text" title="From ${r.source}">${safeUrl(r.url) ? link(r.url, r.text, "plain") : r.text}</span>
          <button class="snooze" data-action="reminder_snooze" data-id="${r.id}" data-days="1" title="Snooze a day">zz</button>
          ${dueChip(r.due)}
        </li>`)}
      </ul>
      ${list.length ? "" : html`<p class="empty">Nothing pending.</p>`}
      <form class="add-reminder" data-action="reminder_add" autocomplete="off">
        <input name="text" placeholder="Add a reminder…" maxlength="200" required>
        <input name="due" type="date" aria-label="Due date">
        <button type="submit">Add</button>
      </form>`,
  });
};

// Restaurant ideas for events near a mealtime: name (website, else directions), distance, and why on hover.
const miles = (km, units) => (units === "metric" ? `${km < 1 ? Math.round(km * 1000) + " m" : km.toFixed(1) + " km"}` : `${(km * 0.621).toFixed(1)} mi`);
const mealLine = (m, units) =>
  m && m.picks && m.picks.length
    ? html`<div class="meal">🍽 ${m.meal[0].toUpperCase() + m.meal.slice(1)} ${m.when === "during" ? "nearby" : m.when}: ${m.picks.map((p, i) => html`${i ? " · " : ""}<span title="${[p.cuisine, p.why].filter(Boolean).join(" — ")}">${link(safeUrl(p.website) || `https://www.google.com/maps/dir/?api=1&destination=${p.lat},${p.lon}`, p.name, "plain")} <span class="tiny">${miles(p.distance_km, units)}</span></span>`)}</div>`
    : "";

const eventRow = (e, note, meal, units) => html`
  <li class="event">
    <span class="when">${e.all_day ? "all day" : timeOf(e.start)}</span>
    <div class="what">
      <div>${safeUrl(e.url) ? link(e.url, e.title, "plain") : e.title}${e.response === "needsAction" ? chip("RSVP?", "warning") : ""}</div>
      ${e.location ? html`<div class="tiny clip">📍 ${e.location}</div>` : ""}
      ${note ? html`<div class="prep">→ ${note}</div>` : ""}
      ${mealLine(meal, units)}
    </div>
    ${navLink(e.location)}
  </li>`;

const agendaCard = (events, b, meals, units) => {
  const notes = Object.fromEntries(((b && b.event_notes) || []).map((n) => [n.event_id, n.note]));
  const row = (e) => eventRow(e, notes[e.id], (meals || {})[e.id], units);
  const now = Date.now();
  const today = localDate();
  const todays = (events || []).filter((e) => eventDate(e) === today && (e.all_day || new Date(e.end) > now));
  const upcoming = (events || []).filter((e) => eventDate(e) > today && eventDate(e) <= addDays(3)).slice(0, 8);
  const byDay = upcoming.reduce((acc, e) => ({ ...acc, [eventDate(e)]: [...(acc[eventDate(e)] || []), e] }), {});
  return card({
    title: "Agenda",
    right: todays.length ? `${todays.length} left today` : "",
    body: html`
      ${todays.length ? html`<ul class="events">${todays.map(row)}</ul>` : empty("Nothing else on the calendar today.")}
      ${Object.entries(byDay).map(([day, evs]) => html`<h4 class="day-label">${dayLabel(day)}</h4><ul class="events">${evs.map(row)}</ul>`)}`,
  });
};

const emailCard = (b, data) => {
  const mails = (b && b.important_emails) || [];
  return card({
    title: "Needs attention",
    right: data.filtered_emails ? `${data.filtered_emails} sensitive skipped` : "",
    body: mails.length
      ? html`<ul class="mails">${mails.map((m) => html`
          <li><a class="mail" href="${safeUrl(m.url) || "#"}" target="_blank" rel="noopener noreferrer" title="${m.from}">
            <div class="clip"><b>${senderName(m.from)}</b> <span class="muted">· ${m.subject}</span></div>
            <div class="sub">${m.why}</div>
            ${m.action ? html`<div class="action">→ ${m.action}</div>` : ""}
          </a></li>`)}</ul>`
      : empty(b ? "Nothing in the inbox needs you." : "Appears with the first briefing."),
  });
};

const comingUpCard = (items) =>
  items && items.length
    ? card({
        title: "Coming up",
        body: items.slice(0, 3).map((ev) => html`
          <div class="research">
            <div class="row between">
              <b class="clip">${safeUrl(ev.url) ? link(ev.url, ev.title, "plain") : ev.title}</b>
              <span class="row gap-s">${navLink(ev.location)}${chip(`${dayLabel(eventDate(ev))}${ev.all_day ? "" : ` ${timeOf(ev.start)}`}`)}</span>
            </div>
            ${ev.location ? html`<div class="tiny clip">📍 ${ev.location}</div>` : ""}
            <p class="sub">${ev.summary}</p>
            <ul class="findings">${(ev.findings || []).slice(0, 5).map(finding)}</ul>
          </div>`),
      })
    : "";

export const render = (payload) => {
  const data = payload.data;
  if (!data) return empty("No data yet: the first refresh is running.");
  const s = payload.summary || {};
  const b = s.briefing;
  // Two independent columns so a short card never leaves a gap beside a tall one. On a phone the columns
  // dissolve and the "o-N" order puts weather and reminders right after the briefing.
  return html`<div class="cols">
    <div class="col main">
      <div class="o-1">${briefingCard(b, payload.summary_generated_at, data.location)}</div>
      <div class="o-4">${agendaCard(data.events, b, s.meals, data.units)}</div>
      <div class="o-6">${comingUpCard(s.coming_up)}</div>
    </div>
    <div class="col">
      <div class="o-2">${nowCard(data, b)}</div>
      <div class="o-3">${remindersCard(data.reminders)}</div>
      <div class="o-5">${emailCard(b, data)}</div>
    </div>
  </div>`;
};
