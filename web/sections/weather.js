// Weather: one card per place (home, cabin…) with conditions, the AI forecaster's take, the week, and SNOTEL.

import { card, chip, compass, dayName, empty, html, link, r0, r1, wmo } from "../lib.js";
import { aiBox, alerts, snotelTable, staleNote, stationStrip, weekStrip } from "./_wx.js";

const KIND_ICON = { home: "🏠", cabin: "🛖", mountain: "⛰" };

const placeCard = (loc, b) => {
  const cur = loc.current || {};
  const [icon, label] = wmo(cur.weather_code, cur.is_day);
  const daily = loc.daily || [];
  const today = daily[0] || {};
  const st = loc.local_stations && loc.local_stations.summary;
  const stations = (loc.local_stations && loc.local_stations.stations) || [];
  const temp = st ? st.median_temp : cur.temperature_2m;
  const nextFreeze = daily.slice(0, 7).find((d) => d.temperature_2m_min <= 32);
  const snow7 = daily.slice(0, 7).reduce((a, d) => a + (d.snowfall_sum || 0), 0);
  const where = [(loc.place || "").split(",").slice(-2).join(",").trim(), loc.elev_ft ? `${loc.elev_ft.toLocaleString()}′` : ""].filter(Boolean).join(" · ");
  const gusty = cur.wind_gusts_10m > cur.wind_speed_10m + 5;
  return card({
    title: `${KIND_ICON[loc.kind] || ""} ${loc.name}`,
    right: where,
    cls: loc.kind === "home" ? "hero" : "",
    body: html`
      ${staleNote(loc)}
      <div class="now">
        <div class="now-icon" title="${label}">${icon}</div>
        <div class="now-temp" title="${st ? `Median of ${st.count} local stations` : "Open-Meteo"}">${r0(temp)}°</div>
        <div class="now-facts">
          <span>${label}</span>
          <span>H ${r0(today.temperature_2m_max)}° · L ${r0(today.temperature_2m_min)}°</span>
          <span>Feels ${r0(cur.apparent_temperature)}° · ${r0(cur.relative_humidity_2m)}% RH</span>
          <span>💨 ${r0(cur.wind_speed_10m)}${gusty ? `–${r0(cur.wind_gusts_10m)}` : ""} mph ${compass(cur.wind_direction_10m)}</span>
        </div>
      </div>
      <div class="chips">
        ${chip(`🥶 ${nextFreeze ? `Freeze ${dayName(nextFreeze.date)} ${r0(nextFreeze.temperature_2m_min)}°` : "No freeze 7d"}`, nextFreeze ? "accent" : "", "First night at or below 32° in the next 7 days")}
        ${snow7 >= 0.1 ? chip(`❄ ${r1(snow7)}″ next 7d`, "accent") : ""}
        ${st ? chip(`📡 ${st.count} stations · ${r0(st.min_temp)}–${r0(st.max_temp)}°`, "", "Live readings from nearby stations") : ""}
      </div>
      ${alerts(loc.alerts)}
      ${aiBox(b)}
      ${weekStrip(daily, snow7 >= 0.1 || loc.kind === "cabin")}
      ${snotelTable(loc.snotel)}
      ${stations.length ? html`<details class="more"><summary>Local stations (${stations.length})</summary>${stationStrip(stations)}</details>` : ""}
      ${loc.nws_periods && loc.nws_periods.length ? html`<details class="more"><summary>NWS forecast</summary>
        <dl class="nws">${loc.nws_periods.map((p) => html`<dt>${p.name}</dt><dd>${p.detail || p.short}</dd>`)}</dl></details>` : ""}
      <p class="links tiny">${link(`https://forecast.weather.gov/MapClick.php?lat=${loc.lat}&lon=${loc.lon}`, "NWS point forecast ↗")}</p>
    `,
  });
};

export const render = (payload) => {
  const data = payload.data;
  if (!data || !data.locations) return empty("No data yet: the first refresh is running.");
  const s = payload.summary || {};
  const byId = s.locations || {};
  return html`
    ${s.headline ? html`<div class="banner">🌤️ ${s.headline}</div>` : ""}
    <div class="grid">${data.locations.map((l) => placeCard(l, byId[l.id]))}</div>`;
};
