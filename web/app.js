// App shell: tabs, polling, the section header (status + refresh buttons), actions, and the settings/cost sheets.
// Each tab's content comes from web/sections/<type>.js, which exports render(payload).

import { ago, dayName, empty, hourLabel, html, money, raw, roundTop, when } from "./lib.js";

const $ = (sel, el = document) => el.querySelector(sel);
const state = { app: null, sections: [], active: null, payloads: {}, modules: {}, sheet: null, usage: null };
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode: fine */ } },
};

// ------------------------------------------------------------------ API

async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, { credentials: "same-origin", ...opts });
  if (res.status === 401) {
    location.href = "/";
    throw new Error("signed out");
  }
  const json = await res.json().catch(() => ({}));
  if (!res.ok && res.status !== 409) throw new Error(json.error || `${res.status}`);
  return json;
}

const toast = (text, bad = false) => {
  const t = $("#toast");
  t.textContent = text;
  t.className = `toast show ${bad ? "bad" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.className = "toast"), 3200);
};

// ------------------------------------------------------------------ tabs

const meta = (id) => state.sections.find((s) => s.id === id);

function renderTabs() {
  $("#tabs").innerHTML = html`${state.sections.map((s, i) => html`
    <a class="tab ${s.id === state.active ? "active" : ""}" href="#${s.id}" data-tab="${s.id}" title="${s.title} (${i + 1})" ${s.id === state.active ? raw('aria-current="page"') : ""}>
      <span class="tab-icon">${s.icon}</span><span class="tab-label">${s.title}</span>
      ${s.status ? html`<i class="busy-dot" title="Updating"></i>` : s.errors && s.errors.length ? html`<i class="err-dot" title="${s.errors.length} problem(s)"></i>` : ""}
    </a>`)}`.s;
  $("#cost-chip").textContent = `$ ${money(state.app.month_cost)}`;
}

function select(id, push = true) {
  if (!meta(id)) id = state.sections[0] && state.sections[0].id;
  if (!id) return;
  const changed = id !== state.active;
  state.active = id;
  store.set("tab", id);
  if (push && location.hash !== `#${id}`) history.replaceState(null, "", `#${id}`);
  renderTabs();
  if (changed) {
    document.title = `${meta(id).title} · ${state.app.title}`;
    renderBar();
    if (state.payloads[id]) renderContent(); else $("#content").innerHTML = '<div class="loading">Loading…</div>';
    window.scrollTo({ top: 0 });
  }
  loadSection(id);
}

// ------------------------------------------------------------------ section

async function loadSection(id) {
  try {
    const payload = await api(`/api/sections/${id}`);
    if (!state.modules[payload.type]) state.modules[payload.type] = await import(`./sections/${payload.type}.js`);
    state.payloads[id] = payload;
    if (id === state.active) {
      renderBar();
      renderContent();
    }
  } catch (e) {
    if (id === state.active) $("#content").innerHTML = html`<p class="empty">Couldn't load this section: ${e.message}</p>`.s;
  }
}

function renderBar() {
  const m = meta(state.active);
  if (!m) return;
  const busy = m.status;
  const errors = m.errors || [];
  const schedule = m.schedule_hours.length ? m.schedule_hours.map(hourLabel).join(", ") : "manual only";
  $("#bar").innerHTML = html`
    <div class="bar-text">
      <h2>${m.icon} ${m.title}</h2>
      <div class="tiny">
        ${busy ? html`<span class="spin"></span> ${busy.text}` : html`Data ${ago(m.generated_at)}${m.has_summary ? html` · AI ${ago(m.summary_generated_at)}` : ""}`}
        ${errors.length ? html` · <button class="linkish warning-text" data-ui="errors">⚠︎ ${errors.length} problem${errors.length > 1 ? "s" : ""}</button>` : ""}
      </div>
    </div>
    <div class="bar-actions">
      <button class="btn" data-ui="refresh" ${busy ? raw("disabled") : ""} title="Refresh the data now. Free: no AI. Runs every ${m.refresh_minutes} min.">↻<span class="lbl"> Refresh</span></button>
      ${m.has_summary ? html`<button class="btn primary" data-ui="summarize" ${busy ? raw("disabled") : ""} title="Write a new AI summary now with ${m.llm.model}. Scheduled: ${schedule}.">✦<span class="lbl"> New AI summary</span></button>` : ""}
      <button class="btn icon" data-ui="settings" title="Settings for ${m.title}">⚙</button>
      ${m.dynamic ? html`<button class="btn icon" data-ui="remove" title="Remove this trip tab">✕</button>` : ""}
    </div>
    <div class="errors" hidden>${errors.map((e) => html`<p>${e}</p>`)}</div>`.s;
}

function renderContent() {
  const payload = state.payloads[state.active];
  const mod = payload && state.modules[payload.type];
  if (!mod) return;
  const content = $("#content");
  // Keep expanded <details> open across re-renders.
  const open = new Set([...content.querySelectorAll("details[open] > summary")].map((s) => s.textContent.trim()));
  try {
    content.innerHTML = String(mod.render(payload));
  } catch (e) {
    console.error(e);
    content.innerHTML = html`<p class="empty">This section failed to render: ${e.message}</p>`.s;
  }
  content.querySelectorAll("details > summary").forEach((s) => open.has(s.textContent.trim()) && (s.parentElement.open = true));
}

// ------------------------------------------------------------------ polling

async function poll() {
  try {
    const app = await api("/api/sections");
    const before = Object.fromEntries(state.sections.map((s) => [s.id, s]));
    state.app = app;
    state.sections = app.sections;
    renderTabs();
    renderBar();
    const was = before[state.active], now = meta(state.active);
    if (now && (!was || was.generated_at !== now.generated_at || was.summary_generated_at !== now.summary_generated_at || !!was.status !== !!now.status)) {
      loadSection(state.active);
    }
  } catch (e) {
    console.warn("poll failed", e);
  }
  const anyBusy = state.sections.some((s) => s.status);
  clearTimeout(poll.timer);
  poll.timer = setTimeout(poll, document.hidden ? 60000 : anyBusy ? 3000 : 15000);
}

// ------------------------------------------------------------------ actions

async function refresh(summary) {
  const id = state.active;
  const res = await api(`/api/sections/${id}/refresh`, { summary });
  toast(res.started ? (summary ? "Writing a new AI summary…" : "Refreshing…") : "Already running.");
  poll();
}

async function removeTab() {
  const m = meta(state.active);
  if (!m || !confirm(`Remove the ${m.title} tab? It won't come back for this trip.`)) return;
  try {
    await api(`/api/sections/${m.id}/remove`, {});
    toast(`Removed ${m.title}.`);
    delete state.payloads[m.id];
    await poll();
    select(state.sections[0].id);
  } catch (e) {
    toast(e.message, true);
  }
}

async function sectionAction(name, body, el) {
  const id = state.active;
  if (el) el.closest("li")?.classList.add("leaving");
  try {
    const res = await api(`/api/sections/${id}/actions/${name}`, body);
    if (res.started) toast("Started.");
    await loadSection(id);
    if (res.started) poll();
  } catch (e) {
    toast(e.message, true);
    loadSection(id);
  }
}

document.addEventListener("click", (ev) => {
  const ui = ev.target.closest("[data-ui]");
  if (ui) {
    const what = ui.dataset.ui;
    if (what === "refresh") return refresh(false);
    if (what === "summarize") return refresh(true);
    if (what === "settings") return openSheet("settings");
    if (what === "remove") return removeTab();
    if (what === "cost") return openSheet("cost");
    if (what === "close") return closeSheet();
    if (what === "errors") return ($("#bar .errors").hidden = !$("#bar .errors").hidden);
    if (what === "prompts") return showPrompts();
    if (what === "set") return saveSetting(ui.dataset.key, JSON.parse(ui.dataset.value));
    if (what === "hour") return toggleHour(+ui.dataset.hour);
    if (what === "interests") return saveInterests();
    return;
  }
  const act = ev.target.closest("button[data-action]");
  if (act) {
    const { action, ...body } = act.dataset;
    sectionAction(action, body, act);
  }
});

document.addEventListener("submit", (ev) => {
  const form = ev.target.closest("form[data-action]");
  if (!form) return;
  ev.preventDefault();
  const body = Object.fromEntries(new FormData(form).entries());
  sectionAction(form.dataset.action, body);
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && state.sheet) return closeSheet();
  if (ev.target.closest("input, textarea, select") || ev.metaKey || ev.ctrlKey || ev.altKey) return;
  const n = parseInt(ev.key, 10);
  if (n >= 1 && n <= state.sections.length) select(state.sections[n - 1].id);
});

window.addEventListener("hashchange", () => select(location.hash.slice(1), false));
document.addEventListener("visibilitychange", () => !document.hidden && poll());

// ------------------------------------------------------------------ sheets (settings, cost)

async function openSheet(kind) {
  state.sheet = kind;
  $("#sheet").hidden = false;
  document.body.classList.add("sheet-open");
  $("#sheet-body").innerHTML = '<div class="loading">Loading…</div>';
  try {
    state.usage = await api("/api/usage");
  } catch { state.usage = null; }
  renderSheet();
}

function closeSheet() {
  state.sheet = null;
  $("#sheet").hidden = true;
  document.body.classList.remove("sheet-open");
}

const MODEL_NAMES = { "claude-sonnet-5-5": "Sonnet 5.5", "claude-opus-5-5": "Opus 5.5", "claude-haiku-4-5": "Haiku 4.5" };
const seg = (key, options, isOn) => html`<div class="seg">${options.map(([v, label]) => html`
  <button class="${isOn(v) ? "on" : ""}" data-ui="set" data-key="${key}" data-value="${JSON.stringify(v)}">${label}</button>`)}</div>`;
const row = (label, hint, control) => html`<div class="setting"><div class="setting-label"><span>${label}</span><span class="tiny">${hint}</span></div>${control}</div>`;

function renderSheet() {
  const body = $("#sheet-body");
  if (state.sheet === "cost") {
    $("#sheet-title").textContent = "AI cost";
    body.innerHTML = costView().s;
    return;
  }
  const m = meta(state.active);
  const p = state.payloads[state.active] || {};
  $("#sheet-title").textContent = `${m.icon} ${m.title} settings`;
  const proj = ((state.usage && state.usage.sections) || []).find((x) => x.section === m.id);
  const local = m.llm.provider !== "anthropic";
  const providers = [[null, "Claude (Anthropic)"], ...state.app.providers.map((name) => [name, `${name} model`])];
  const privacy = p.privacy;
  const draft = $("#interests") ? $("#interests").value : state.app.interests.join("\n"); // keep unsaved edits across re-renders
  body.innerHTML = html`
    ${m.has_summary ? html`
      <div class="callout">
        <div class="tiny">AI cost at these settings</div>
        <div class="big">${local ? "Free (local model)" : html`≈ ${money(proj ? proj.per_month : null)}<span class="sub"> / month</span>`}</div>
        ${proj && !local ? html`<div class="tiny">${proj.per_day}× daily · about ${money(proj.per_run)} per run${proj.based_on ? ` (avg of last ${proj.based_on})` : " (typical)"} · ${money(proj.month)} so far this month</div>` : ""}
      </div>
      ${row("Model provider", "", seg("llm.profile", providers, (v) => (p.llm_profile || null) === v))}
      ${local ? "" : row("Model", "Opus finds more, costs ~2×", seg("llm.model", state.app.models.map((id) => [id, MODEL_NAMES[id] || id]), (v) => v === m.llm.model))}
      ${local ? "" : row("Thinking effort", "", seg("llm.effort", [["low", "low"], ["medium", "medium"], ["high", "high"]], (v) => v === m.llm.effort))}
      ${row("Web searches per run", "1¢ each + reading", seg("llm.max_searches", [0, 2, 4, 6, 9, 12].map((n) => [n, n === 0 ? "none" : `≤ ${n}`]), (v) => v === m.llm.max_searches))}
      ${row("AI summary times", m.schedule_hours.length ? `${m.schedule_hours.length}× per day` : "manual only", html`
        <div class="hours">${Array.from({ length: 24 }, (_, h) => html`<button class="${m.schedule_hours.includes(h) ? "on" : ""}" data-ui="hour" data-hour="${h}">${hourLabel(h)}</button>`)}</div>`)}
    ` : ""}
    ${m.uses_interests ? html`
      <div class="setting">
        <div class="setting-label"><span>Your interests</span><span class="tiny">one per line · shared by Today, Local and trips</span></div>
        <textarea id="interests" class="interests" rows="8" placeholder="e.g. craft breweries and good local food">${draft}</textarea>
        <button class="btn" data-ui="interests">Save interests</button>
      </div>` : ""}
    ${row("Data refresh", "free: no AI", seg("refresh_minutes", [10, 15, 20, 30, 60].map((n) => [n, `${n} min`]), (v) => v === m.refresh_minutes))}
    ${m.has_summary ? html`
      <div class="setting">
        <div class="setting-label"><span>What gets sent</span><span class="tiny">${local ? "to your local model" : "to Anthropic"}</span></div>
        <button class="btn" data-ui="prompts">Show the prompts from the last run</button>
        <div id="prompts"></div>
      </div>` : ""}
    ${privacy ? html`
      <div class="setting">
        <div class="setting-label"><span>Privacy</span><span class="tiny">edit in config.json</span></div>
        <dl class="kv">${Object.entries(privacy).map(([k, v]) => html`<dt>${k.replaceAll("_", " ")}</dt><dd>${Array.isArray(v) ? (v.length ? v.join(", ") : "none") : String(v)}</dd>`)}</dl>
      </div>` : ""}
    <p class="tiny">Changes save to config.json right away and apply to the next run.</p>`.s;
}

async function saveSetting(key, value) {
  try {
    await api(`/api/sections/${state.active}/settings`, { key, value });
    await poll();
    await loadSection(state.active);
    state.usage = await api("/api/usage").catch(() => state.usage);
    if (state.sheet) renderSheet();
  } catch (e) {
    toast(e.message, true);
  }
}

async function saveInterests() {
  try {
    const { interests } = await api("/api/interests", { interests: $("#interests").value.split("\n") });
    state.app.interests = interests;
    toast(`Saved ${interests.length} interest${interests.length === 1 ? "" : "s"}: the next research run uses them.`);
  } catch (e) {
    toast(e.message, true);
  }
}

function toggleHour(h) {
  const hours = meta(state.active).schedule_hours;
  saveSetting("summary.schedule_hours", hours.includes(h) ? hours.filter((x) => x !== h) : [...hours, h].sort((a, b) => a - b));
}

async function showPrompts() {
  const box = $("#prompts");
  box.innerHTML = '<div class="loading">Loading…</div>';
  const prompts = await api(`/api/sections/${state.active}/prompts`);
  const calls = Object.entries(prompts);
  box.innerHTML = (calls.length
    ? html`${calls.map(([call, p]) => html`
        <details class="prompt">
          <summary><b>${call}</b> <span class="tiny">${p.provider} · ${p.model} · ${when(p.time)} · ${(p.user || "").length.toLocaleString()} chars${p.web_searches ? ` · ≤${p.web_searches} searches` : " · no web"}</span></summary>
          <h5>System</h5><pre>${p.system}</pre>
          <h5>Message</h5><pre>${p.user}</pre>
        </details>`)}`
    : empty("Nothing sent yet: this appears after the first AI summary.")).s;
}

function costView() {
  const u = state.usage;
  if (!u) return empty("Cost data unavailable.");
  const daily = u.daily || [];
  const max = Math.max(0.5, ...daily.map((d) => d.cost));
  const W = 340, H = 60, slot = W / Math.max(1, daily.length), bw = Math.min(14, slot - 4);
  const peak = daily.reduce((a, d) => (d.cost > a.cost ? d : a), daily[0] || { cost: 0 });
  const bars = daily.map((d, i) => {
    const h = (d.cost / max) * (H - 12);
    const x = i * slot + (slot - bw) / 2;
    return `<g><title>${dayName(d.date)} ${d.date.slice(5)}: ${money(d.cost)}</title>` +
      (h > 0.5 ? `<path class="bar" d="${roundTop(x, H - h, bw, h, Math.min(3, h))}"/>` : "") +
      (d === peak && d.cost > 0 ? `<text class="peak" x="${x + bw / 2}" y="${H - h - 3}" text-anchor="middle">${money(d.cost)}</text>` : "") +
      (i === 0 || i === daily.length - 1 ? `<text class="axis" x="${x + bw / 2}" y="${H + 11}" text-anchor="middle">${i === daily.length - 1 ? "today" : d.date.slice(5)}</text>` : "") + "</g>";
  });
  const title = (sid) => (meta(sid) || { title: sid }).title;
  return html`
    <div class="stats">
      ${[["Today", u.today], ["7 days", u.week], ["This month", u.month]].map(([l, v]) => html`<div class="stat"><b>${money(v)}</b><span>${l}</span></div>`)}
    </div>
    ${raw(`<svg class="costchart" viewBox="0 0 ${W} ${H + 14}"><line class="base" x1="0" x2="${W}" y1="${H}" y2="${H}"/>${bars.join("")}</svg>`)}
    <div class="callout">
      <span class="sub">At current settings: </span><b>≈ ${money(u.projected_month)}/month</b>
      <table class="proj">${u.sections.map((p) => html`<tr>
        <td>${title(p.section)}</td>
        <td class="tiny">${p.provider === "anthropic" ? (MODEL_NAMES[p.model] || p.model) : "local"} · ${p.per_day}×/day · ~${money(p.per_run)}/run</td>
        <td class="num">${money(p.per_month)}</td></tr>`)}</table>
    </div>
    <h4 class="caps tiny">Recent AI calls</h4>
    <table class="recent">${(u.recent || []).map((r) => html`<tr title="${(r.input || 0).toLocaleString()} input + ${(r.output || 0).toLocaleString()} output tokens, ${r.searches} searches">
      <td>${new Date(r.time).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</td>
      <td>${title(r.section || "")} <span class="tiny">${r.call || ""}${r.ok ? "" : " · failed"}</span></td>
      <td class="tiny">${Math.round(((r.input || 0) + (r.output || 0)) / 1000)}k · ${r.searches || 0}🔎</td>
      <td class="num">${money(r.cost)}</td></tr>`)}</table>
    <p class="tiny">All-time ${money(u.all_time)} over ${u.count} calls. Data refreshes are free; only AI summaries cost.</p>`;
}

// ------------------------------------------------------------------ start

(async function start() {
  try {
    state.app = await api("/api/sections");
  } catch (e) {
    $("#content").innerHTML = html`<p class="empty">Can't reach the server: ${e.message}</p>`.s;
    return;
  }
  state.sections = state.app.sections;
  $("#app-title").textContent = state.app.title;
  $("#today").textContent = new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  if (!state.sections.length) {
    $("#content").innerHTML = empty("No sections are enabled in config.json.").s;
    return;
  }
  select(location.hash.slice(1) || store.get("tab"));
  poll();
  setInterval(() => !document.hidden && renderBar(), 30000); // keep "5m ago" honest between changes
})();
