// Shared helpers for section renderers: safe HTML templating, formatting, weather codes.

// ------------------------------------------------------------------ templating
// html`...` escapes every interpolated value unless it's raw() (or another html`` result), so text from
// email, calendars and web pages can never become markup.

export class Raw {
  constructor(s) { this.s = s; }
  toString() { return this.s; }
}
export const raw = (s) => new Raw(String(s));
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);
const fmt = (v) => {
  if (v == null || v === false || v === true) return "";
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(fmt).join("");
  return esc(v);
};
export const html = (strings, ...vals) => raw(strings.reduce((out, s, i) => out + s + (i < vals.length ? fmt(vals[i]) : ""), ""));

// Links come from email, calendars and web pages: only http(s) gets through.
export const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//i.test(u) ? u : null);
export const link = (url, text, cls = "link") => {
  const u = safeUrl(url);
  return u ? html`<a class="${cls}" href="${u}" target="_blank" rel="noopener noreferrer">${text}</a>` : html`<span>${text}</span>`;
};

// ------------------------------------------------------------------ formatting

export const r0 = (v) => (v == null ? "–" : Math.round(v));
export const r1 = (v) => (v == null ? "–" : Math.round(v * 10) / 10);
export const money = (v) => (v == null ? "–" : v < 1 ? `${Math.round(v * 100)}¢` : `$${v.toFixed(2)}`);
export const dayName = (iso, short = true) =>
  new Date(iso + "T12:00:00").toLocaleDateString("en-US", { weekday: short ? "short" : "long" });
export const ago = (iso) => {
  if (!iso) return "never";
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
};
export const compass = (deg) => (deg == null ? "" : ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(deg / 45) % 8]);
export const localDate = (d = new Date()) => d.toLocaleDateString("en-CA"); // YYYY-MM-DD
export const addDays = (n) => localDate(new Date(Date.now() + n * 86400000));
export const timeOf = (iso) =>
  new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).replace(":00", "").replace(" ", "").toLowerCase();
export const dayLabel = (iso) => {
  if (iso === localDate()) return "Today";
  if (iso === addDays(1)) return "Tomorrow";
  return new Date(iso + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
};
export const hourLabel = (h) => (h === 0 ? "12am" : h === 12 ? "12pm" : `${h % 12}${h < 12 ? "am" : "pm"}`);
export const when = (iso) =>
  iso ? new Date(iso).toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";

// ------------------------------------------------------------------ weather codes (WMO)

const WMO = {
  0: ["☀️", "Clear"], 1: ["🌤️", "Mostly clear"], 2: ["⛅", "Partly cloudy"], 3: ["☁️", "Overcast"],
  45: ["🌫️", "Fog"], 48: ["🌫️", "Freezing fog"],
  51: ["🌦️", "Light drizzle"], 53: ["🌦️", "Drizzle"], 55: ["🌧️", "Heavy drizzle"],
  56: ["🌧️", "Freezing drizzle"], 57: ["🌧️", "Freezing drizzle"],
  61: ["🌦️", "Light rain"], 63: ["🌧️", "Rain"], 65: ["🌧️", "Heavy rain"],
  66: ["🌧️", "Freezing rain"], 67: ["🌧️", "Freezing rain"],
  71: ["🌨️", "Light snow"], 73: ["🌨️", "Snow"], 75: ["❄️", "Heavy snow"], 77: ["🌨️", "Snow grains"],
  80: ["🌦️", "Showers"], 81: ["🌧️", "Showers"], 82: ["⛈️", "Heavy showers"],
  85: ["🌨️", "Snow showers"], 86: ["❄️", "Heavy snow showers"],
  95: ["⛈️", "Thunderstorm"], 96: ["⛈️", "Thunderstorm, hail"], 99: ["⛈️", "Thunderstorm, hail"],
};
export const wmo = (code, isDay = 1) => {
  const [icon, label] = WMO[code] || ["·", ""];
  return [!isDay && code <= 1 ? "🌙" : icon, label];
};

// ------------------------------------------------------------------ small building blocks

export const card = ({ title, right, cls = "", body }) => html`
  <section class="card ${cls}">
    ${title || right ? html`<header class="card-head"><h3>${title}</h3>${right ? html`<span class="tiny">${right}</span>` : ""}</header>` : ""}
    ${body}
  </section>`;

export const chip = (text, cls = "", title = "") => html`<span class="chip ${cls}" title="${title}">${text}</span>`;

export const empty = (text) => html`<p class="empty">${text}</p>`;

// Rect with rounded top corners only (data end), square at the baseline.
export const roundTop = (x, y, w, h, r) =>
  `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;

export const confidenceDots = (level) => {
  const levels = ["low", "medium", "high"];
  const n = levels.indexOf(level);
  return html`<span class="dots" title="${level} confidence">${levels.map((_, i) => html`<i class="${i <= n ? "on" : ""}"></i>`)}</span>`;
};

// ------------------------------------------------------------------ research findings

export const CATEGORY_ICON = {
  event: "🎟", schedule: "🗓", venue: "📍", travel: "🚗", outdoors: "🥾", "food & drink": "🍽", music: "🎶",
  culture: "🏛", sports: "🏅", family: "👨‍👩‍👧", news: "📰", conditions: "🌲", tip: "💡",
};

// Google Maps directions; opened while signed in, it shows up as a recent destination in the car.
export const navLink = (place) =>
  place ? link(`https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(place)}`, "🚗", "nav") : "";

export const finding = (f) => html`
  <li><a class="finding" href="${safeUrl(f.url) || "#"}" target="_blank" rel="noopener noreferrer" title="${f.why}">
    <span class="ficon">${CATEGORY_ICON[f.category] || "•"}</span>
    <span><span class="ftitle">${f.title}</span><span class="tiny">${[f.when, f.where].filter(Boolean).join(" · ") || f.why}</span></span>
  </a></li>`;
