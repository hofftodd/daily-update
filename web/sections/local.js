// Local: what's happening and worth knowing around wherever you are, shaped by your interests (config.json).

import { CATEGORY_ICON, ago, card, dayLabel, empty, html, finding, safeUrl } from "../lib.js";

const tripDates = (t) => {
  const d = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  return t.start === t.end ? d(t.start) : `${d(t.start)} – ${d(t.end)}`;
};

const aroundCard = (s, here, trip) =>
  card({
    title: s ? `Around ${s.place}` : here ? `Around ${here}` : "Around here",
    right: html`${s ? `researched ${ago(s.researched_at)} ` : ""}<button class="mini" data-action="explore" title="Research the current area again (uses web search)">🔎 Explore</button>`,
    body: s
      ? html`
        ${here && s.place !== here ? html`<p class="tiny warning-text">You've moved: new research for ${here} is queued.</p>` : ""}
        ${trip ? html`<p class="tiny">✈️ ${tripDates(trip)} · ${trip.purpose}</p>` : ""}
        <p class="lede">${s.events ? s.events.summary : ""}</p>`
      : trip
        ? html`<p class="tiny">✈️ ${tripDates(trip)} · ${trip.purpose}</p>${empty("Research for this trip is on its way.")}`
        : empty("Research runs at the scheduled times, when you move somewhere new, or when you tap 🔎 Explore."),
  });

// The day is already the group heading, so the second line is the place and why it fits them.
const eventItem = (e) => html`
  <li><a class="finding" href="${safeUrl(e.url) || "#"}" target="_blank" rel="noopener noreferrer">
    <span class="ficon">${CATEGORY_ICON[e.category] || "•"}</span>
    <span><span class="ftitle">${e.title}</span><span class="tiny">${[e.where, e.why].filter(Boolean).join(" · ")}</span></span>
  </a></li>`;

const eventsCard = (ev) => {
  const items = (ev && ev.events) || [];
  const groups = items.reduce((acc, e) => {
    const key = e.date || "ongoing";
    return { ...acc, [key]: [...(acc[key] || []), e] };
  }, {});
  return card({
    title: "Coming up nearby",
    right: items.length ? `${items.length} events` : "",
    body: items.length
      ? Object.entries(groups).map(([day, evs]) => html`
          <h4 class="day-label">${day === "ongoing" ? "Ongoing" : dayLabel(day)}</h4>
          <ul class="findings">${evs.map(eventItem)}</ul>`)
      : empty(ev ? "Nothing matching your interests turned up." : "Appears after the first research run."),
  });
};

const infoCard = (info) =>
  card({
    title: "Good to know",
    body: info
      ? html`<p class="sub">${info.summary}</p><ul class="findings">${(info.findings || []).map(finding)}</ul>`
      : empty("Appears after the first research run."),
  });

export const render = (payload) => {
  const data = payload.data;
  if (!data) return empty("No data yet: the first refresh is running.");
  const s = payload.summary;
  return html`<div class="local">
    ${aroundCard(s, data.location && data.location.label, data.trip)}
    <div class="local-cols">
      ${eventsCard(s && s.events)}
      <div class="local-side">${infoCard(s && s.info)}</div>
    </div>
  </div>`;
};
