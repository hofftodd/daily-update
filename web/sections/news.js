// News: the day's top stories with a moderate summary, and how progressive, moderate and conservative outlets framed
// each one. Every link is a real headline from the feeds; the model only cites them by id.

import { ago, card, chip, empty, html, link } from "../lib.js";

const LEANS = ["progressive", "moderate", "conservative"];
const LABEL = { progressive: "Progressive", moderate: "Moderate", conservative: "Conservative" };
const CATEGORY_ICON = {
  politics: "🏛", world: "🌍", economy: "📈", business: "💼", technology: "💻", science: "🔬", health: "🩺",
  climate: "🌡", justice: "⚖️", culture: "🎭", sports: "🏅", other: "📰",
};

const legend = () => html`<span class="lean-legend">${LEANS.map((l) => html`<span><i class="lean-swatch ${l}"></i>${LABEL[l]}</span>`)}</span>`;

// Share of a story's cited headlines from each side, left to right.
const spectrum = (coverage) => {
  const total = LEANS.reduce((a, l) => a + (coverage[l] || 0), 0) || 1;
  return html`<div class="spectrum" role="img" aria-label="${LEANS.map((l) => `${LABEL[l]} ${coverage[l] || 0}`).join(", ")} headlines">
    ${LEANS.map((l) => (coverage[l] ? html`<span class="${l}" style="flex:${coverage[l] / total}" title="${LABEL[l]}: ${coverage[l]} headline${coverage[l] === 1 ? "" : "s"}">${coverage[l]}</span>` : ""))}
  </div>`;
};

const overviewCard = (s, data, at) =>
  card({
    title: "⚖️ The moderate summary",
    right: ago(at),
    cls: "hero",
    body: html`
      <p class="lede">${s.overview}</p>
      <h4 class="day-label">What each side is focused on</h4>
      <div class="lean-cols">
        ${LEANS.map((l) => html`<div class="lean-col ${l}"><span class="lean-name">${LABEL[l]}</span><p>${s.focus[l]}</p></div>`)}
      </div>
      ${sourcesLine(data)}
      <p class="tiny">Surveyed ${s.headline_count} headlines.</p>`,
  });

const sourcesLine = (data) => html`<div class="chips">
  ${(data.sources || []).map((src) => chip(html`<i class="lean-swatch ${src.lean}"></i>${src.name}${src.ok ? "" : " ⚠"}`, src.ok ? "" : "warning",
    src.ok ? `${LABEL[src.lean]} · ${src.count} headlines` : "Feed unavailable on the last refresh"))}
</div>`;

// One row per story: who covered it, at a glance.
const coverageCard = (stories) =>
  card({
    title: "Who's covering what",
    body: html`<div class="coverage">
      ${stories.map((st) => html`<div class="coverage-row">
        <span class="coverage-title clip" title="${st.title}">${CATEGORY_ICON[st.category] || "•"} ${st.title}</span>
        ${spectrum(st.coverage)}
      </div>`)}
    </div>
    <p class="tiny">${legend()} · Bar widths are each side's share of the headlines about that story; a missing color is a blind spot.</p>`,
  });

const viewpoint = (st, lean) => {
  const take = st.viewpoints[lean];
  const heads = st.headlines.filter((h) => h.lean === lean).slice(0, 3);
  return html`<div class="lean-col ${lean}">
    <span class="lean-name">${LABEL[lean]}</span>
    ${take ? html`<p>${take}</p>` : html`<p class="muted">Not covered by ${lean} outlets today.</p>`}
    ${heads.length ? html`<ul class="lean-heads">${heads.map((h) => html`<li>${link(h.url, h.title)} <span class="tiny">${h.source}</span></li>`)}</ul>` : ""}
  </div>`;
};

const storyCard = (st) => {
  const missing = LEANS.filter((l) => !st.coverage[l]);
  return card({
    title: html`${CATEGORY_ICON[st.category] || "•"} ${st.title}`,
    right: missing.length && missing.length < 3 ? chip(`Blind spot: ${missing.map((l) => LABEL[l]).join(", ")}`, "warning") : st.category,
    cls: "story",
    body: html`
      ${spectrum(st.coverage)}
      <p class="story-summary">${st.summary}</p>
      ${st.contested ? html`<p class="contested"><b>Disputed:</b> ${st.contested}</p>` : ""}
      <div class="lean-cols">${LEANS.map((l) => viewpoint(st, l))}</div>`,
  });
};

// The raw survey, so there's something to read before the first summary and a way to see what was left out.
const headlinesCard = (data) => {
  const heads = data.headlines || [];
  return card({
    title: "All headlines",
    right: `${heads.length} from ${(data.sources || []).filter((s) => s.ok).length} outlets`,
    body: html`<details class="more"><summary>Show every headline by side</summary>
      <div class="lean-cols">
        ${LEANS.map((l) => html`<div class="lean-col ${l}">
          <span class="lean-name">${LABEL[l]}</span>
          <ul class="lean-heads">${heads.filter((h) => h.lean === l).map((h) => html`<li>${link(h.url, h.title)} <span class="tiny">${h.source}</span></li>`)}</ul>
        </div>`)}
      </div></details>`,
  });
};

export const render = (payload) => {
  const data = payload.data;
  if (!data) return empty("No data yet: the first refresh is running.");
  const s = payload.summary;
  return html`<div class="news">
    ${s ? html`
      <div class="banner">📰 ${s.headline}</div>
      ${overviewCard(s, data, payload.summary_generated_at)}
      ${s.stories.length ? coverageCard(s.stories) : ""}
      ${s.stories.map(storyCard)}`
    : card({ title: "⚖️ The moderate summary", body: html`${empty("The summary appears after the first AI run, or tap ✦ New AI summary.")}${sourcesLine(data)}` })}
    ${headlinesCard(data)}
  </div>`;
};
