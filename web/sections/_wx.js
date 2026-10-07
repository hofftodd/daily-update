// Weather building blocks shared by the Weather and Ski sections.

import { ago, chip, compass, dayName, html, link, r0, r1, raw, roundTop, wmo } from "../lib.js";

export const alerts = (list) =>
  list && list.length
    ? html`<div class="chips">${list.map((a) =>
        chip(`⚠︎ ${a.event}`, a.severity === "Severe" || a.severity === "Extreme" ? "critical" : "warning", a.headline || ""))}</div>`
    : "";

// 7-day columns: day, icon, floating hi/lo bar on a shared scale, precip chance, snow.
export const weekStrip = (daily, showSnow) => {
  const days = (daily || []).slice(0, 7);
  if (!days.length) return "";
  const lo = Math.min(...days.map((d) => d.temperature_2m_min));
  const hi = Math.max(...days.map((d) => d.temperature_2m_max));
  const pct = (t) => ((t - lo) / Math.max(1, hi - lo)) * 100;
  return html`<div class="week">${days.map((d, i) => {
    const [icon, label] = wmo(d.weather_code);
    const pop = d.precipitation_probability_max;
    const tip = `${dayName(d.date, false)}: ${label}, ${r0(d.temperature_2m_max)}° / ${r0(d.temperature_2m_min)}°${pop != null ? `, ${pop}% precip` : ""}${d.snowfall_sum ? `, ${r1(d.snowfall_sum)}″ snow` : ""}`;
    return html`<div class="day" title="${tip}">
      <div class="tiny ${i === 0 ? "strong" : ""}">${i === 0 ? "Today" : dayName(d.date)}</div>
      <div class="wx-icon">${icon}</div>
      <div class="hi">${r0(d.temperature_2m_max)}°</div>
      <div class="range"><span style="bottom:${pct(d.temperature_2m_min).toFixed(1)}%;top:${(100 - pct(d.temperature_2m_max)).toFixed(1)}%"></span></div>
      <div class="tiny">${r0(d.temperature_2m_min)}°</div>
      <div class="pop ${pop >= 20 ? "" : "faint"}">${pop ?? "–"}%</div>
      ${showSnow ? html`<div class="tiny ${d.snowfall_sum >= 0.1 ? "strong" : ""}">${d.snowfall_sum >= 0.1 ? `❄${r1(d.snowfall_sum)}″` : "·"}</div>` : ""}
    </div>`;
  })}</div>`;
};

const shortName = (name) => name.replace(/^COAC\s+/i, "").replace(/\s+Station$/i, "").replace(/\s+(EB|WB|NB|SB)\s+at\s+/, " ");

// Live readings from chosen mesonet stations, highest first (inversions jump out).
export const stationStrip = (stations) => {
  if (!stations || !stations.length) return "";
  const sorted = [...stations].sort((a, b) => (b.elev_ft || 0) - (a.elev_ft || 0));
  return html`<div class="rows stations">${sorted.map((s) => html`
    <div class="srow ${s.stale ? "stale" : ""}" title="${s.name} (${s.id}) · observed ${ago(s.time)}${s.humidity != null ? ` · RH ${s.humidity}%` : ""}">
      <span class="name">📡 ${shortName(s.name)}</span>
      <span class="tiny">${s.elev_ft ? `${s.elev_ft.toLocaleString()}′` : ""}</span>
      <b>${r0(s.temp)}°</b>
      <span class="tiny">${s.wind != null ? `${s.wind}${s.gust_3h ? `–${s.gust_3h}` : ""} ${compass(s.wind_dir)}` : ""}</span>
      <span class="tiny">${ago(s.time)}</span>
    </div>`)}</div>`;
};

// Tiny 14-day snow-depth trend for a SNOTEL station.
const spark = (points, width = 56, height = 16) => {
  if (!points || points.length < 2) return html`<svg width="${width}" height="${height}"></svg>`;
  const vals = points.map((p) => p.value);
  const max = Math.max(6, ...vals);
  const x = (i) => (i / (points.length - 1)) * width;
  const y = (v) => height - 1 - (v / max) * (height - 2);
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  return raw(`<svg width="${width}" height="${height}" class="spark"><path class="area" d="${d} L${width},${height} L0,${height} Z"/><path class="line" d="${d}"/></svg>`);
};

export const snotelTable = (sites) =>
  sites && sites.length
    ? html`<div class="snotel">
        <div class="snotel-row head"><span>SNOTEL</span><span>Elev</span><span>Temp</span><span>Depth</span><span>14 days</span><span>SWE</span></div>
        ${sites.map((s) => html`
          <a class="snotel-row" href="${s.url}" target="_blank" rel="noopener noreferrer"
             title="${s.name} (${s.id}) · observed ${ago(s.time)} · 24h low ${r0(s.temp_min_24h)}° · 24h depth change ${s.depth_change_24h ?? "–"}″ · 72h precip ${s.precip_72h ?? "–"}″">
            <span class="name">${s.name}</span>
            <span class="tiny">${s.elev_ft ? `${(s.elev_ft / 1000).toFixed(1)}k′` : ""}</span>
            <b>${r0(s.temp)}°</b>
            <b>${r0(s.snow_depth)}″${s.depth_change_24h > 0 ? html`<small class="accent"> +${r0(s.depth_change_24h)}</small>` : ""}</b>
            ${spark(s.depth_14d)}
            <span class="tiny">${r1(s.swe)}″</span>
          </a>`)}
      </div>`
    : "";

export const expertTakes = (takes) =>
  (takes || []).map((t) => html`<p class="take"><b>🎙 ${t.source}</b> ${t.take} ${t.url ? link(t.url, "↗") : ""}</p>`);

export const sourcesList = (sources) =>
  sources && sources.length
    ? html`<details class="more"><summary>Sources (${sources.length})</summary><ul class="sources">${sources.map((s) => html`<li>${link(s.url, s.title)}</li>`)}</ul></details>`
    : "";

// The AI's take on one place: headline, outlook, notes, expert takes.
export const aiBox = (b, emptyText = "The AI summary appears after the first scheduled run.") => {
  if (!b) return html`<p class="empty">${emptyText}</p>`;
  return html`<div class="ai">
    <div class="ai-head">${b.headline}</div>
    ${b.outlook ? html`<p>${b.outlook}</p>` : ""}
    ${b.notes && b.notes.length ? html`<div class="chips">${b.notes.map((n) => chip(n))}</div>` : ""}
    ${b.access ? html`<p class="access">🚗 ${b.access}</p>` : ""}
    ${expertTakes(b.expert_takes)}
    ${sourcesList(b.sources)}
  </div>`;
};

// snow-forecast.com reports AM/PM/night periods labelled "Saturday 3"; sum per day of month.
const sfcByDate = (loc) => {
  const sf = loc.snow_forecast;
  if (!sf) return {};
  const byDom = {};
  for (const p of sf.periods) {
    const dom = parseInt((p.day || "").split(" ").pop(), 10);
    if (!isNaN(dom)) byDom[dom] = (byDom[dom] || 0) + (p.snow || 0);
  }
  const out = {};
  for (const d of loc.daily || []) {
    const dom = parseInt(d.date.slice(8), 10);
    if (dom in byDom) out[d.date] = byDom[dom];
  }
  return out;
};

// 10-day snow chart: bar = model mean, whisker = model range, diamond = snow-forecast.com.
export const snowChart = (loc) => {
  const days = (loc.snow_models || []).slice(0, 10);
  if (!days.length) return "";
  const width = 360, height = 104;
  const sfc = sfcByDate(loc);
  const maxV = Math.max(2, ...days.map((d) => Math.max(d.max || 0, sfc[d.date] || 0)));
  const top = 14, bottom = 16, plotH = height - top - bottom;
  const slot = width / days.length;
  const barW = Math.min(18, slot - 8);
  const y = (v) => top + plotH - (v / maxV) * plotH;
  const peak = days.reduce((a, d) => ((d.mean || 0) > (a.mean || 0) ? d : a), days[0]);
  const tick = maxV > 12 ? 6 : maxV > 6 ? 3 : 1;
  let svg = "";
  for (let t = tick; t <= maxV; t += tick) {
    svg += `<line class="grid" x1="0" x2="${width}" y1="${y(t)}" y2="${y(t)}"/><text class="axis" x="${width}" y="${y(t) - 2}" text-anchor="end">${t}″</text>`;
  }
  svg += `<line class="base" x1="0" x2="${width}" y1="${y(0)}" y2="${y(0)}"/>`;
  days.forEach((d, i) => {
    const cx = i * slot + slot / 2;
    const mean = d.mean || 0;
    const h = Math.max(0, y(0) - y(mean));
    const tip = `${dayName(d.date, false)} ${d.date.slice(5)}\n` +
      Object.entries(d.models).map(([m, v]) => `${m}: ${v == null ? "–" : r1(v) + "″"}`).join("\n") +
      (d.date in sfc ? `\nsnow-forecast.com: ${r1(sfc[d.date])}″` : "");
    svg += `<g><title>${tip.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</title><rect x="${i * slot}" y="0" width="${slot}" height="${height}" fill="transparent"/>`;
    if (h > 0.5) svg += `<path class="bar" d="${roundTop(cx - barW / 2, y(mean), barW, h, Math.min(4, h))}"/>`;
    if (d.max > d.min && (d.max || 0) > 0.05) {
      svg += `<g class="whisker"><line x1="${cx}" x2="${cx}" y1="${y(d.min)}" y2="${y(d.max)}"/><line x1="${cx - 3}" x2="${cx + 3}" y1="${y(d.max)}" y2="${y(d.max)}"/></g>`;
    }
    if (d.date in sfc && sfc[d.date] > 0.05) {
      const sx = cx + barW / 2 + 3, sy = y(sfc[d.date]);
      svg += `<rect class="sfc" x="${sx - 4}" y="${sy - 4}" width="8" height="8" transform="rotate(45 ${sx} ${sy})"/>`;
    }
    if (d === peak && mean >= 0.5) svg += `<text class="peak" x="${cx}" y="${y(d.max || mean) - 4}" text-anchor="middle">${r1(mean)}″</text>`;
    svg += `<text class="axis ${i === 0 ? "strong" : ""}" x="${cx}" y="${height - 3}" text-anchor="middle">${i === 0 ? "Tdy" : dayName(d.date).slice(0, 2)}</text></g>`;
  });
  return html`<div class="chart">
    ${raw(`<svg class="snowchart" viewBox="0 0 ${width} ${height}" role="img" aria-label="10-day snowfall forecast">${svg}</svg>`)}
    <div class="legend tiny">
      <span><i class="key bar"></i>model avg</span>
      <span><i class="key whisker"></i>model range</span>
      ${loc.snow_forecast ? html`<span><i class="key sfc"></i>snow-forecast.com</span>` : ""}
    </div>
  </div>`;
};

export const miniBars = (loc, scaleMax) => {
  const days = (loc.snow_models || []).slice(0, 7);
  const W = 12, gap = 3, H = 20;
  const bars = days.map((d, i) => {
    const h = Math.max(0, ((d.mean || 0) / scaleMax) * H);
    return `<g><title>${dayName(d.date)}: ${r1(d.mean)}″ (models ${r1(d.min)}–${r1(d.max)}″)</title>` +
      `<rect class="grid-fill" x="${i * (W + gap)}" y="${H - 1}" width="${W}" height="1"/>` +
      (h > 0.5 ? `<path class="bar" d="${roundTop(i * (W + gap), H - h, W, h, Math.min(2, h))}"/>` : "") + "</g>";
  });
  return raw(`<svg class="minibars" width="${days.length * (W + gap)}" height="${H}">${bars.join("")}</svg>`);
};

export const staleNote = (loc) => (loc.stale_since ? html`<p class="tiny warning-text">Showing data from ${ago(loc.stale_since)}: the latest fetch failed.</p>` : "");
