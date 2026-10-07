// Ski: regional snow outlook, home mountain in depth, avalanche forecast, and the other mountains at a glance.

import { ago, card, chip, compass, confidenceDots, dayName, empty, html, link, localDate, r0, r1, raw, wmo } from "../lib.js";
import { aiBox, alerts, miniBars, snowChart, staleNote, stationStrip } from "./_wx.js";

const isOpen = (status) => /\bopen\b/i.test(status || "") && !/clos|opens/i.test(status || "");
const range = (lo, hi) => (r0(lo) === r0(hi) ? `${r0(lo)}″` : `${r0(lo)}–${r0(hi)}″`);

const statusChip = (status) =>
  status ? html`<span class="chip status" title="${status}"><i class="dot ${isOpen(status) ? "good" : ""}"></i>${status}</span>` : "";

// ------------------------------------------------------------------ regional outlook

const CHARACTER_ICON = { none: "☀️", "cold powder": "❄️", mixed: "🌨️", "heavy wet": "💧", "rain/snow mix": "🌧️" };
const QUALITY = { "cold powder": "❄️", medium: "🌨️", "heavy wet": "💧", "rain/mix": "🌧️", none: "" };

// Without an AI summary, build a plain outlook from the home mountain's model snowfall.
const modelOutlook = (mtn) => {
  if (!mtn || !mtn.snow_models) return null;
  const daily = Object.fromEntries((mtn.daily || []).map((d) => [d.date, d]));
  const days = mtn.snow_models.slice(0, 7).map((d) => {
    const v = d.mean || 0;
    const tmax = (daily[d.date] || {}).temperature_2m_max;
    return {
      date: d.date, inches: v, snow_level_ft: null,
      intensity: v < 0.1 ? "none" : v < 3 ? "light" : v < 8 ? "moderate" : "heavy",
      quality: v < 0.1 ? "none" : tmax != null && tmax <= 25 ? "cold powder" : "medium",
    };
  });
  const total = days.reduce((a, d) => a + d.inches, 0);
  const peak = days.reduce((a, d) => (d.inches > a.inches ? d : a), days[0]);
  return {
    headline: total < 0.5 ? "No snow in the 7-day models" : `~${r0(total)}″ in the models, peaking ${dayName(peak.date, false)}`,
    summary: `Model average for ${mtn.name}'s summit. The AI summary adds timing, snow quality and expert takes.`,
    storm_character: total < 0.5 ? "none" : "mixed",
    peak_day: total < 0.5 ? null : peak.date,
    confidence: null, days, fromModels: true,
  };
};

const outlookCard = (outlook, at) => {
  if (!outlook) return "";
  const today = localDate();
  const days = (outlook.days || []).filter((d) => d.date >= today).slice(0, 7);
  return card({
    title: "Snow outlook",
    right: outlook.fromModels ? "from models" : `AI · ${ago(at)}`,
    cls: "hero",
    body: html`
      <div class="outlook-head">${CHARACTER_ICON[outlook.storm_character] || "🏔️"} ${outlook.headline}</div>
      <p class="sub">${outlook.summary}</p>
      ${outlook.confidence ? html`<p class="tiny">${confidenceDots(outlook.confidence)} ${outlook.confidence} confidence</p>` : ""}
      <div class="outlook-days">${days.map((d) => {
        const peak = d.date === outlook.peak_day;
        const tip = `${dayName(d.date, false)}: ${d.intensity}${d.quality !== "none" ? `, ${d.quality}` : ""}${d.snow_level_ft ? ` · snow level ~${Math.round(d.snow_level_ft / 100) * 100} ft` : ""}`;
        return html`<div class="oday ${peak ? "peak" : ""}" title="${tip}">
          <div class="tiny strong">${peak ? "PEAK" : raw("&nbsp;")}</div>
          <div class="obar-wrap"><div class="obar ${d.intensity}"></div></div>
          <div class="oq">${QUALITY[d.quality] || ""}</div>
          <div class="tiny">${d.date === today ? "Today" : dayName(d.date)}</div>
        </div>`;
      })}</div>
      <div class="legend tiny center">
        ${["light", "moderate", "heavy"].map((k) => html`<span><i class="key obar ${k}"></i>${k}</span>`)}
        <span>❄️ powder</span><span>💧 wet</span>
      </div>`,
  });
};

// ------------------------------------------------------------------ home mountain

const homeCard = (loc, b) => {
  const cur = loc.current || {};
  const base = loc.base_current || {};
  const sr = (b && b.snow_report) || {};
  const exp = b && b.expected_snow_7d;
  const models7 = Object.values(loc.snow_7d || {});
  const span = exp ? [exp.low_in, exp.high_in] : models7.length ? [Math.min(...models7), Math.max(...models7)] : null;
  const [icon, label] = wmo(cur.weather_code, cur.is_day);
  const stat = (value, name, title = "") => html`<div class="stat" title="${title}"><b>${value}</b><span>${name}</span></div>`;
  return card({
    title: `⛰ ${loc.name}`,
    right: statusChip(sr.status),
    cls: "hero",
    body: html`
      ${staleNote(loc)}
      <div class="stats">
        ${stat(`${icon} ${r0(cur.temperature_2m)}°`, "Summit", `Summit ${loc.summit_elev_ft} ft: ${label}`)}
        ${stat(`${r0(base.temperature_2m)}°`, "Base", `Base ${loc.base_elev_ft} ft`)}
        ${stat(r0(cur.wind_gusts_10m), "Gust mph", `Wind ${r0(cur.wind_speed_10m)} mph ${compass(cur.wind_direction_10m)}`)}
        ${stat(sr.base_depth_in != null ? `${r0(sr.base_depth_in)}″` : "–", "Base depth")}
        ${stat(sr.new_24h_in != null ? `${r0(sr.new_24h_in)}″` : "–", "New 24h")}
      </div>
      <div class="next7">
        <div><div class="tiny caps">Next 7 days</div><div class="big">❄ ${span ? range(span[0], span[1]) : "–"}</div></div>
        <div class="right">
          ${exp ? html`<div class="sub">${confidenceDots(exp.confidence)} ${exp.confidence} confidence</div>` : ""}
          ${b && b.best_day ? html`<div class="sub">Best: ${b.best_day}</div>` : ""}
          ${sr.lifts_open ? html`<div class="tiny">Lifts ${sr.lifts_open}${sr.trails_open ? ` · trails ${sr.trails_open}` : ""}</div>` : ""}
        </div>
      </div>
      ${snowChart(loc)}
      ${alerts(loc.alerts)}
      ${aiBox(b)}
      ${loc.local_stations && loc.local_stations.stations && loc.local_stations.stations.length
        ? html`<details class="more"><summary>Mountain stations</summary>${stationStrip(loc.local_stations.stations)}</details>` : ""}
      <p class="links tiny">
        ${loc.website ? link(loc.website, "Resort conditions ↗") : ""}
        ${loc.snow_forecast ? link(loc.snow_forecast.url, "snow-forecast.com ↗") : ""}
      </p>`,
  });
};

// ------------------------------------------------------------------ avalanche

// North American Public Avalanche Danger Scale (always paired with the level name).
const DANGER = { 1: "Low", 2: "Moderate", 3: "Considerable", 4: "High", 5: "Extreme" };
const BANDS = [["upper", "Above treeline"], ["middle", "Near treeline"], ["lower", "Below treeline"]];
const ASPECTS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"];

// Aspect/elevation rose: 8 aspects around, upper elevation in the centre ring.
const aspectRose = (location, size = 44) => {
  const c = size / 2, R = c - 1, rings = { upper: [0, 0.36], middle: [0.36, 0.68], lower: [0.68, 1] };
  const set = new Set(location);
  const pt = (a, r) => [c + r * Math.sin(a), c - r * Math.cos(a)];
  let paths = "";
  ASPECTS.forEach((asp, i) => {
    for (const [band, [f0, f1]] of Object.entries(rings)) {
      const a0 = ((i - 0.5) * Math.PI) / 4, a1 = ((i + 0.5) * Math.PI) / 4, r0_ = f0 * R, r1_ = f1 * R;
      const [x0, y0] = pt(a0, r1_), [x1, y1] = pt(a1, r1_), [x2, y2] = pt(a1, r0_), [x3, y3] = pt(a0, r0_);
      const d = `M${x0},${y0} A${r1_},${r1_} 0 0 1 ${x1},${y1} L${x2},${y2} ${r0_ > 0 ? `A${r0_},${r0_} 0 0 0 ${x3},${y3}` : ""} Z`;
      paths += `<path class="${set.has(`${asp} ${band}`) ? "on" : ""}" d="${d}"/>`;
    }
  });
  return raw(`<svg class="rose" width="${size}" height="${size}">${paths}<text x="${c}" y="7" text-anchor="middle">N</text></svg>`);
};

const dangerBands = (levels, compact) => html`<div class="bands ${compact ? "compact" : ""}">${BANDS.map(([key, label], i) => {
  const lvl = levels ? levels[key] : null;
  const name = DANGER[lvl] || "No rating";
  return html`<div class="band" title="${label}: ${lvl > 0 ? `${lvl} - ${name}` : name}">
    <span class="swatch d${lvl || 0}" style="--inset:${(2 - i) * (compact ? 4 : 8)}px"></span>
    ${compact ? "" : html`<span class="sub">${lvl > 0 ? `${lvl} ${name}` : name}</span>`}
  </div>`;
})}</div>`;

const avalancheCard = (av) => {
  if (!av) return "";
  const head = { title: `⚠︎ Avalanche · ${av.label || ""}`, right: av.link ? link(av.link, `${av.zone || "forecast"} ↗`) : av.zone };
  // Re-check expiry at render time: the data may be older than the forecast's validity window.
  const expired = av.expired || !av.expires || new Date(av.expires) <= new Date();
  if (expired) {
    return card({ ...head, body: html`<div class="row gap">${dangerBands(null, true)}
      <span class="sub">No current forecast${av.expires ? ` · last one expired ${new Date(av.expires).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}` : ""}</span></div>` });
  }
  const today = av.danger && av.danger.current;
  const tomorrow = av.danger && av.danger.tomorrow;
  const active = av.product_type === "forecast" && today;
  return card({
    ...head,
    body: html`
      <div class="row gap top wrap">
        <div><div class="tiny">Today</div>${dangerBands(active ? today : null)}</div>
        ${active && tomorrow ? html`<div><div class="tiny">Tmrw</div>${dangerBands(tomorrow, true)}</div>` : ""}
        ${active && av.problems.length ? html`<div class="problems">${av.problems.slice(0, 3).map((p) => html`
          <div class="row gap-s" title="${p.name}: ${p.likelihood}, size ${(p.size || []).join("–")} · ${p.location.join(", ")}">
            ${aspectRose(p.location)}
            <div><div class="strong small">${p.name}</div><div class="tiny">${p.likelihood} · D${(p.size || []).join("–")}</div></div>
          </div>`)}</div>` : ""}
      </div>
      ${active ? "" : html`<p class="sub">No danger rating published.</p>`}
      <p class="tiny">Valid until ${new Date(av.expires).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit" })}</p>
      ${av.bottom_line ? html`<details class="more"><summary>${(av.bottom_line || "").split(/(?<=[.!?])\s/)[0]}</summary>
        <p class="pre">${av.bottom_line}</p><p class="tiny">${av.author} · published ${new Date(av.published).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</p></details>` : ""}`,
  });
};

// ------------------------------------------------------------------ other mountains

const othersCard = (locs, byId) => {
  if (!locs.length) return "";
  const scaleMax = Math.max(2, ...locs.flatMap((l) => (l.snow_models || []).slice(0, 7).map((d) => d.mean || 0)));
  return card({
    title: "Other mountains",
    right: "summit · 7-day snow",
    body: html`<div class="mtns">${locs.map((loc) => {
      const b = byId[loc.id];
      const sr = (b && b.snow_report) || {};
      const exp = b && b.expected_snow_7d;
      const mean7 = (loc.snow_models || []).slice(0, 7).reduce((a, d) => a + (d.mean || 0), 0);
      const [icon] = wmo((loc.current || {}).weather_code);
      return html`<details class="mtn">
        <summary>
          <span class="name">${loc.name}</span>
          <i class="dot ${isOpen(sr.status) ? "good" : ""}" title="${sr.status || "status unknown"}"></i>
          <span>${icon} ${r0((loc.current || {}).temperature_2m)}°</span>
          ${miniBars(loc, scaleMax)}
          <b>${exp ? range(exp.low_in, exp.high_in) : `${r1(mean7)}″`}</b>
        </summary>
        <div class="mtn-body">
          ${sr.status ? html`<p class="sub">${statusChip(sr.status)} ${sr.base_depth_in != null ? `Base ${r0(sr.base_depth_in)}″` : ""}</p>` : ""}
          ${aiBox(b, "No AI summary for this mountain yet.")}
          <p class="links tiny">${loc.website ? link(loc.website, "Resort ↗") : ""} ${loc.snow_forecast ? link(loc.snow_forecast.url, "snow-forecast.com ↗") : ""}</p>
        </div>
      </details>`;
    })}</div>`,
  });
};

export const render = (payload) => {
  const data = payload.data;
  if (!data || !data.locations) return empty("No data yet: the first refresh is running.");
  const s = payload.summary || {};
  const byId = s.mountains || {};
  const home = data.locations.find((l) => l.id === data.home_mountain);
  const others = data.locations.filter((l) => l !== home);
  return html`<div class="grid">
    ${outlookCard(s.outlook || modelOutlook(home), payload.summary_generated_at)}
    ${home ? homeCard(home, byId[home.id]) : ""}
    ${avalancheCard(data.avalanche)}
    ${othersCard(others, byId)}
  </div>`;
};
