"use strict";

const $ = (s, el = document) => el.querySelector(s);
const SEL = ["Local", "Empate", "Visita"];
const pct = (x, d = 0) => (x == null ? "–" : (x * 100).toFixed(d).replace(".", ",") + "%");
const num = (x, d = 2) => (x == null ? "–" : Number(x).toFixed(d).replace(".", ","));
const signed = (x, d = 1) => (x == null ? "–" : (x > 0 ? "+" : "") + (x * 100).toFixed(d).replace(".", ",") + "%");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Fechas sin hora ("2026-01-01") se leen a mediodía local para que la zona horaria no las corra un día.
const fmtDate = (iso, withTime = true) => new Intl.DateTimeFormat("es-CL", withTime
  ? { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }
  : { day: "numeric", month: "short", year: "numeric" }).format(new Date(iso.length === 10 ? iso + "T12:00:00" : iso));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

const cache = {};
async function api(path, opts) {
  if (!opts && cache[path]) return cache[path];
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  const data = await r.json();
  if (!opts) cache[path] = data;
  return data;
}

/* ---------- tema ---------- */
function setTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { t ? localStorage.setItem("theme", t) : localStorage.removeItem("theme"); } catch (e) { /* sin storage */ }
  redrawCharts();
}
try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* */ }
$("#theme").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  setTheme(dark ? "light" : "dark");
});

/* ---------- navegación ---------- */
const views = { inicio: renderHome, partidos: renderMatches, combinadas: () => renderCombos(), sugeridas: () => renderSuggestions(), resultados: renderTracking,
  rendimiento: renderBacktest, simulador: renderSimulator, "como-funciona": () => {} };
const rendered = new Set();
function route() {
  const id = (location.hash || "#inicio").slice(1);
  const key = id in views ? id : "inicio";
  document.querySelectorAll("section.view").forEach((s) => s.classList.toggle("active", s.id === "v-" + key));
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + key));
  if (!rendered.has(key) || key === "combinadas") {          // combinadas se redibuja: depende del boleto
    rendered.add(key);
    Promise.resolve(views[key]()).catch((e) => showError("v-" + key, e));
  }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
function showError(id, e) {
  const el = document.getElementById(id);
  el.insertAdjacentHTML("beforeend", `<div class="callout warn" style="margin-top:16px">No se pudieron cargar los datos: ${esc(e.message)}</div>`);
}

/* ---------- gráficos ---------- */
const charts = {};
const chartDefs = {};
function chart(id, build) {
  chartDefs[id] = build;
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), build());
}
function redrawCharts() { Object.keys(chartDefs).forEach((id) => chart(id, chartDefs[id])); }
function baseOptions(extra = {}) {
  const grid = css("--grid"), text = css("--text-2");
  return {
    responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { position: "top", align: "start", labels: { color: text, boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 3, font: { size: 12 } } },
      tooltip: { backgroundColor: css("--surface"), titleColor: css("--text"), bodyColor: text, borderColor: css("--border"),
        borderWidth: 1, padding: 10, cornerRadius: 8, boxPadding: 4, usePointStyle: true },
    },
    scales: {
      x: { grid: { color: grid, drawTicks: false }, border: { display: false }, ticks: { color: text, font: { size: 11.5 }, padding: 6 } },
      y: { grid: { color: grid, drawTicks: false }, border: { display: false }, ticks: { color: text, font: { size: 11.5 }, padding: 6 } },
    },
    ...extra,
  };
}

/* ---------- componentes ---------- */
function probBar(p) {
  if (!p) return `<div class="probbar"><div style="flex:1;background:var(--surface-2);color:var(--muted)">sin datos</div></div>`;
  const cls = ["h", "d", "a"];
  return `<div class="probbar" role="img" aria-label="Local ${pct(p[0])}, empate ${pct(p[1])}, visita ${pct(p[2])}">${
    p.map((x, i) => `<div class="${cls[i]}" style="flex:${x}" title="${SEL[i]}: ${pct(x, 1)}">${x >= 0.12 ? pct(x) : ""}</div>`).join("")}</div>`;
}
function miniBar(p) {
  const c = ["var(--home)", "var(--draw)", "var(--away)"];
  return `<span class="mini" title="L ${pct(p[0])} · E ${pct(p[1])} · V ${pct(p[2])}">${p.map((x, i) => `<i style="flex:${x};background:${c[i]}"></i>`).join("")}</span>`;
}
function stat(label, value, hint = "") {
  return `<div class="card stat"><div class="label">${label}</div><div class="value num">${value}</div>${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
}
const SOURCE_PILL = { "modelo + mercado": "good", modelo: "", mercado: "warn", "sin datos": "", error: "bad" };

/* ---------- INICIO ---------- */
async function renderHome() {
  const o = await api("/api/overview");
  const b = o.backtest, t = o.tracking;
  $("#hero-acc").innerHTML = `${pct(b.acc_official, 1)} <small>de ${b.n.toLocaleString("es-CL")} partidos</small>`;
  $("#hero-sub").textContent = `Partidos de ${b.leagues} ligas entre ${fmtDate(b.from, false)} y ${fmtDate(b.to, false)}, que el sistema no había visto al elegir sus parámetros.`;
  $("#hero-note").innerHTML = `<div><b>¿50% es poco?</b> Hay tres resultados posibles: adivinando al azar se acierta 33%, y siempre al local ${pct(b.acc_naive_home)}.
    Las casas de apuestas, con toda su información, rondan el ${pct(b.acc_market)}. Lo importante no es solo acertar, sino que
    las probabilidades sean <b>honestas</b> (gráfico de la derecha).</div>`;
  $("#hero-stats").innerHTML = [
    ["Siempre al local", pct(b.acc_naive_home, 1), "estrategia ingenua"],
    ["Modelo solo", pct(b.acc_model, 1), "Elo + Dixon-Coles"],
    ["Casas de apuestas", pct(b.acc_market, 1), "cuotas de cierre"],
  ].map(([l, v, h]) => `<div class="stat"><div class="label">${l}</div><div class="value num" style="font-size:22px">${v}</div><div class="hint">${h}</div></div>`).join("");

  const evalTxt = t.evaluated ? `${pct(t.hit_rate)} de acierto` : "aún sin resultados";
  $("#home-tiles").innerHTML = [
    stat("Predicciones en seguimiento", (t.evaluated + t.pending).toLocaleString("es-CL"), `${t.evaluated} evaluadas · ${evalTxt}`),
    stat("Ligas con modelo validado", o.n_leagues_model, "más Chile con probabilidades de mercado"),
    stat("Recomendación por defecto", "No apostar", "sin ventaja demostrada frente al mercado"),
    stat("Última actualización", o.last_daily_run ? new Intl.DateTimeFormat("es-CL", { day: "numeric", month: "short" }).format(new Date(o.last_daily_run)) : "–",
      o.last_daily_run ? `a las ${new Intl.DateTimeFormat("es-CL", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(o.last_daily_run))} · modelo ${o.model_version}` : ""),
  ].join("");

  chart("ch-confidence", () => ({
    type: "bar",
    data: {
      labels: o.confidence.map((c) => c.range),
      datasets: [
        { label: "Probabilidad que dio el sistema", data: o.confidence.map((c) => c.pred * 100), backgroundColor: css("--official"), borderRadius: 4, maxBarThickness: 24, borderSkipped: "start" },
        { label: "Acierto real", data: o.confidence.map((c) => c.hit * 100), backgroundColor: css("--model"), borderRadius: 4, maxBarThickness: 24, borderSkipped: "start" },
      ],
    },
    options: baseOptions({
      plugins: { ...baseOptions().plugins, tooltip: { ...baseOptions().plugins.tooltip,
        callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(1)}%`,
          footer: (items) => `${o.confidence[items[0].dataIndex].n.toLocaleString("es-CL")} partidos` } } },
      scales: { ...baseOptions().scales, y: { ...baseOptions().scales.y, min: 0, max: 100, ticks: { ...baseOptions().scales.y.ticks, callback: (v) => v + "%" } },
        x: { ...baseOptions().scales.x, title: { display: true, text: "Seguridad del sistema en su pronóstico", color: css("--muted"), font: { size: 11.5 } } } },
    }),
  }));
}

/* ---------- PRÓXIMOS PARTIDOS ---------- */
let leagueFilter = "Todas";
async function renderMatches() {
  const list = await api("/api/upcoming");
  const leagues = ["Todas", ...new Set(list.map((m) => m.league_name))];
  const draw = () => {
    $("#league-filter").innerHTML = leagues.map((l) => `<button class="chip ${l === leagueFilter ? "on" : ""}" data-l="${esc(l)}">${esc(l)}${
      l === "Todas" ? ` (${list.length})` : ""}</button>`).join("");
    const shown = list.filter((m) => leagueFilter === "Todas" || m.league_name === leagueFilter);
    $("#matches").innerHTML = shown.length ? shown.map(matchCard).join("")
      : `<div class="card empty" style="grid-column:1/-1">No hay partidos programados en los próximos 7 días para las ligas seguidas
         (puede ser fecha FIFA). La tarea diaria agrega partidos y cuotas a medida que se publican.</div>`;
  };
  $("#league-filter").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    leagueFilter = b.dataset.l; draw();
  });
  draw();
}
function matchCard(m) {
  const p = m.p_official;
  const fav = p ? p.indexOf(Math.max(...p)) : null;
  const r = m.recommendation || {};
  const reco = r.bet
    ? `<span class="pill warn">Valor marginal</span> ${SEL[r.sel]} a ${num(r.odds)} (${esc(r.book)}, EV ${signed(r.ev)}) · solo en papel`
    : `<span class="pill">No apostar</span> ${esc(r.text || "")}`;
  let extra = "";
  if (m.xg) {
    extra = `<div class="kv">
      <div><span>Goles esperados</span><b class="num">${num(m.xg[0], 1)} – ${num(m.xg[1], 1)}</b></div>
      <div><span>Marcador más probable</span><b class="num">${esc(m.top_scores[0][0])}</b></div>
      <div><span>Más de 2,5 goles</span><b class="num">${pct(m.over25)}</b></div>
      <div><span>Ambos marcan</span><b class="num">${pct(m.btts)}</b></div></div>`;
  }
  let oddsHtml = "";
  const book = m.odds_1x2 && (m.odds_1x2.Bet365 ? "Bet365" : Object.keys(m.odds_1x2)[0]);
  if (book) {
    const o = m.odds_1x2[book];
    const fair = p ? p.map((x) => 1 / x) : null;
    oddsHtml = `<div class="compare">
      <div class="odds-row"><span>Cuota ${esc(book)}</span>${o.map((x) => `<span><b>${num(x)}</b></span>`).join("")}</div>
      ${fair ? `<div class="odds-row"><span>Cuota justa</span>${fair.map((x, i) => `<span title="${o[i] > x ? "La casa paga más que la cuota justa" : "La casa paga menos que la cuota justa"}">${num(x)}</span>`).join("")}</div>` : ""}
      <div class="odds-row" style="color:var(--muted)"><span>Si apuestas 1.000</span>${o.map((x) => `<span>gana ${Math.round(x * 1000 - 1000).toLocaleString("es-CL")}</span>`).join("")}</div></div>`;
  } else if (p) {
    oddsHtml = `<div class="compare"><div class="odds-row"><span>Cuota justa</span>${p.map((x) => `<span>${num(1 / x)}</span>`).join("")}</div>
      <div style="color:var(--muted)">Cuotas de la casa: aún no publicadas o no recolectadas.</div></div>`;
  }
  let compare = "";
  if (m.p_model && m.p_market) {
    compare = `<div class="compare">
      <div class="row"><span></span><span>Local</span><span>Empate</span><span>Visita</span></div>
      <div class="row"><span>Modelo</span>${m.p_model.map((x) => `<span class="num">${pct(x)}</span>`).join("")}</div>
      <div class="row"><span>Mercado</span>${m.p_market.map((x) => `<span class="num">${pct(x)}</span>`).join("")}</div></div>`;
  }
  return `<article class="card match">
    <div class="meta"><span>${esc(m.league_name)}</span><span>${fmtDate(m.kickoff)}</span></div>
    <div class="teams"><div class="t">${esc(m.home)}</div><div class="vs">vs</div><div class="t r">${esc(m.away)}</div></div>
    <div>${probBar(p)}</div>
    <div class="reco"><span class="pill ${SOURCE_PILL[m.source] ?? ""}">${esc(m.source)}</span>
      ${fav != null ? `<span>Más probable: <b style="color:var(--text)">${fav === 1 ? "empate" : fav === 0 ? esc(m.home) : esc(m.away)}</b></span>` : ""}</div>
    ${oddsHtml}${extra}${compare}
    ${m.stale ? `<div class="stale">⚠ Datos de la liga hasta ${fmtDate(m.data_through, false)}: faltan fechas recientes (la fuente se atrasó).</div>` : ""}
    <div class="reco">${reco}</div>
    ${m.options && m.options.length ? `<button class="chip" style="justify-self:start" onclick="goToCombos('${esc(m.ref)}')">Ver todas las opciones y combinar →</button>` : ""}
  </article>`;
}

/* ---------- RESULTADOS ---------- */
async function renderTracking() {
  const d = await api("/api/tracking");
  const s = d.summary;
  const llTxt = s.ll_market != null
    ? `sistema ${num(s.ll_official_same, 3)} vs mercado ${num(s.ll_market, 3)}` : "sin cuotas de referencia aún";
  $("#trk-tiles").innerHTML = [
    stat("Partidos evaluados", s.evaluated, `${s.pending} esperando resultado`),
    stat("Acierto del pronóstico", s.evaluated ? pct(s.hit_rate) : "–", s.evaluated < 100 ? "muestra todavía pequeña" : ""),
    stat("Log loss (menor es mejor)", s.evaluated ? num(s.ll_official, 3) : "–", llTxt),
    stat("Apuestas en papel", s.paper_bets, s.paper_bets ? `${num(s.bets_profit, 1)} u · CLV medio ${signed(s.bets_clv)}` : "ninguna aún"),
  ].join("");
  $("#trk-table").innerHTML = d.matches.length ? `<table>
    <thead><tr><th>Fecha</th><th>Liga</th><th>Partido</th><th>Probabilidades</th><th>Pronóstico</th><th class="r">Resultado</th><th></th><th>Versión</th></tr></thead>
    <tbody>${d.matches.map((m) => `<tr>
      <td>${fmtDate(m.kickoff)}</td><td>${esc(m.league)}</td><td>${esc(m.home)} – ${esc(m.away)}</td>
      <td>${miniBar(m.p_official)} <span class="num" style="color:var(--muted);font-size:12px">${m.p_official.map((x) => pct(x)).join(" · ")}</span></td>
      <td>${SEL[m.pick]} <span class="num" style="color:var(--muted)">(${pct(m.p_official[m.pick])})</span></td>
      <td class="r"><b>${esc(m.score)}</b></td>
      <td>${m.hit ? '<span class="pill good">✓ acierto</span>' : '<span class="pill bad">✗ fallo</span>'}</td>
      <td><span class="pill">${esc(m.version)}</span></td></tr>`).join("")}</tbody></table>`
    : `<div class="empty">Todavía no terminan partidos con predicción registrada.</div>`;
  $("#trk-bets").innerHTML = d.bets.length ? `<table>
    <thead><tr><th>Fecha</th><th>Partido</th><th>Selección</th><th class="r">Cuota</th><th class="r">EV</th><th class="r">CLV</th><th class="r">Resultado</th><th>Versión</th></tr></thead>
    <tbody>${d.bets.map((b) => `<tr><td>${fmtDate(b.kickoff)}</td><td>${esc(b.partido)}</td><td>${SEL["HDA".indexOf(b.sel)]} (${esc(b.book)})</td>
      <td class="r">${num(b.odds)}</td><td class="r">${signed(b.ev)}</td><td class="r">${signed(b.clv)}</td>
      <td class="r">${b.won ? `<span class="pill good">+${num(b.profit)} u</span>` : '<span class="pill bad">−1 u</span>'}</td>
      <td><span class="pill">${esc(b.version)}</span></td></tr>`).join("")}</tbody></table>`
    : `<div class="empty">Sin apuestas en papel registradas.</div>`;
}

/* ---------- RENDIMIENTO ---------- */
async function renderBacktest() {
  const d = await api("/api/backtest");
  const s = d.summary, bm = d.betting.model_only, bo = d.betting.official_v2;
  $("#bt-intro").textContent = `Evaluación sobre ${s.n.toLocaleString("es-CL")} partidos de ${s.leagues} ligas (${fmtDate(s.from, false)} – ${fmtDate(s.to, false)}). ` +
    `Los pesos se ajustaron con datos de 2016-2025, así que estos partidos son "examen" para el modelo.`;
  $("#bt-tiles").innerHTML = [
    stat("Probabilidad oficial (modelo + mercado)", pct(s.acc_official, 1), `log loss ${num(s.ll_official, 4)}`),
    stat("Mercado solo", pct(s.acc_market, 1), `log loss ${num(s.ll_market, 4)}`),
    stat("Modelo solo", pct(s.acc_model, 1), `log loss ${num(s.ll_model, 4)}`),
  ].join("") + (s.ou ? [
    stat("Más/Menos de 2,5 goles: oficial", pct(s.ou.acc_official, 1), `log loss ${num(s.ou.ll_official, 4)} · ${s.ou.n.toLocaleString("es-CL")} partidos`),
    stat("Más/Menos de 2,5: mercado", pct(s.ou.acc_market, 1), `log loss ${num(s.ou.ll_market, 4)}`),
    stat("Más/Menos de 2,5: modelo solo", pct(s.ou.acc_model, 1), `log loss ${num(s.ou.ll_model, 4)}`),
  ].join("") : "");

  chart("ch-calib", () => {
    const pts = (k) => d.calibration[k].map((c) => ({ x: c.pred * 100, y: c.obs * 100, n: c.n }));
    return {
      type: "scatter",
      data: { datasets: [
        { label: "Calibración perfecta", data: [{ x: 0, y: 0 }, { x: 100, y: 100 }], showLine: true, borderColor: css("--muted"), borderWidth: 1, pointRadius: 0, borderDash: [] },
        { label: "Probabilidad oficial", data: pts("official"), showLine: true, borderColor: css("--official"), backgroundColor: css("--official"), borderWidth: 2, pointRadius: 4.5, pointBorderColor: css("--surface"), pointBorderWidth: 2 },
        { label: "Modelo solo", data: pts("model"), showLine: true, borderColor: css("--model"), backgroundColor: css("--model"), borderWidth: 2, pointRadius: 4.5, pointBorderColor: css("--surface"), pointBorderWidth: 2 },
      ] },
      options: baseOptions({
        interaction: { mode: "nearest", intersect: false },
        plugins: { ...baseOptions().plugins, tooltip: { ...baseOptions().plugins.tooltip, filter: (i) => i.datasetIndex > 0,
          callbacks: { label: (c) => `${c.dataset.label}: dijo ${c.parsed.x.toFixed(0)}%, ocurrió ${c.parsed.y.toFixed(0)}% (${c.raw.n.toLocaleString("es-CL")})` } } },
        scales: {
          x: { ...baseOptions().scales.x, type: "linear", min: 0, max: 100, title: { display: true, text: "Probabilidad que dio el sistema", color: css("--muted") }, ticks: { ...baseOptions().scales.x.ticks, callback: (v) => v + "%" } },
          y: { ...baseOptions().scales.y, min: 0, max: 100, title: { display: true, text: "Frecuencia real", color: css("--muted") }, ticks: { ...baseOptions().scales.y.ticks, callback: (v) => v + "%" } },
        },
      }),
    };
  });

  chart("ch-betting", () => {
    const toPts = (c) => c.curve.map((p, i) => ({ x: i / Math.max(1, c.curve.length - 1) * 100, y: p.u, d: p.d }));
    return {
      type: "scatter",
      data: { datasets: [
        { label: `Modelo solo (${bm.n.toLocaleString("es-CL")} apuestas)`, data: toPts(bm), showLine: true, borderColor: css("--model"), backgroundColor: css("--model"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 5 },
        { label: `v2: modelo + mercado, cuota ≤ 4 (${bo.n} apuestas)`, data: toPts(bo), showLine: true, borderColor: css("--official"), backgroundColor: css("--official"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 5 },
      ] },
      options: baseOptions({
        interaction: { mode: "nearest", intersect: false, axis: "x" },
        plugins: { ...baseOptions().plugins, tooltip: { ...baseOptions().plugins.tooltip,
          callbacks: { title: (i) => i[0].raw.d, label: (c) => `${c.dataset.label.split(" (")[0]}: ${c.parsed.y > 0 ? "+" : ""}${c.parsed.y} u` } } },
        scales: {
          x: { ...baseOptions().scales.x, type: "linear", min: 0, max: 100, title: { display: true, text: "Avance de la temporada 2026 (% de apuestas)", color: css("--muted") }, ticks: { ...baseOptions().scales.x.ticks, callback: (v) => v + "%" } },
          y: { ...baseOptions().scales.y, title: { display: true, text: "Unidades ganadas/perdidas", color: css("--muted") } },
        },
      }),
    };
  });

  chart("ch-buckets", () => ({
    type: "bar",
    data: { labels: bm.buckets.map((b) => b.range), datasets: [{ label: "Rendimiento por unidad", data: bm.buckets.map((b) => b.yield * 100),
      backgroundColor: bm.buckets.map((b) => (b.yield < 0 ? css("--bad") : css("--good"))), borderRadius: 4, maxBarThickness: 24, borderSkipped: "start" }] },
    options: baseOptions({
      plugins: { ...baseOptions().plugins, legend: { display: false }, tooltip: { ...baseOptions().plugins.tooltip,
        callbacks: { label: (c) => `${c.parsed.y.toFixed(1)}% por unidad · ${bm.buckets[c.dataIndex].n} apuestas` } } },
      scales: { x: { ...baseOptions().scales.x, title: { display: true, text: "Cuota apostada", color: css("--muted") } },
        y: { ...baseOptions().scales.y, ticks: { ...baseOptions().scales.y.ticks, callback: (v) => v + "%" } } },
    }),
  }));

  const ci = (b) => (b.ci ? `IC95% [${signed(b.ci[0])}; ${signed(b.ci[1])}]` : "");
  $("#bt-reading").innerHTML = `
    <p><b style="color:var(--text)">Las probabilidades son confiables.</b> En la calibración, la línea oficial va pegada a la diagonal:
      cuando el sistema dice 60%, ocurre cerca del 60% de las veces.</p>
    <p><b style="color:var(--text)">Pero no le gana al mercado.</b> El modelo solo acierta ${pct(s.acc_model, 1)} vs ${pct(s.acc_market, 1)} de las casas.
      Combinado con las cuotas iguala al mercado (${pct(s.acc_official, 1)}), sin superarlo.</p>
    <p><b style="color:var(--text)">Apostar con el modelo solo pierde:</b> ${signed(bm.yield)} por unidad en ${bm.n.toLocaleString("es-CL")} apuestas (${ci(bm)}).
      La versión v2 apuesta mucho menos y pierde menos (${signed(bo.yield)}, ${ci(bo)}), pero tampoco demuestra ganancia.</p>
    <p>Conclusión: úsalo para <b style="color:var(--text)">entender</b> partidos, no para apostar.</p>`;

  const best = (r) => Math.min(r.ll_model, r.ll_market, r.ll_official);
  $("#bt-leagues").innerHTML = `<table>
    <thead><tr><th>Liga</th><th class="r">Partidos</th><th class="r">Acierto modelo</th><th class="r">Acierto mercado</th><th class="r">Acierto oficial</th>
      <th class="r">Log loss modelo</th><th class="r">Log loss mercado</th><th class="r">Log loss oficial</th><th>Estado</th></tr></thead>
    <tbody>${d.per_league.map((r) => `<tr><td>${esc(r.name)} <span style="color:var(--muted)">${esc(r.code)}</span></td><td class="r">${r.n}</td>
      <td class="r">${pct(r.acc_model, 1)}</td><td class="r">${pct(r.acc_market, 1)}</td><td class="r">${pct(r.acc_official, 1)}</td>
      ${["ll_model", "ll_market", "ll_official"].map((k) => `<td class="r" ${r[k] === best(r) ? 'style="font-weight:650;color:var(--text)"' : 'style="color:var(--text-2)"'}>${num(r[k], 3)}</td>`).join("")}
      <td><span class="pill ${r.status.startsWith("pasó") ? "warn" : ""}" title="${esc(r.status)}">${r.status.startsWith("pasó") ? "en observación" : "sin ventaja"}</span></td></tr>`).join("")}</tbody></table>`;
}

/* ---------- SIMULADOR ---------- */
async function renderSimulator() {
  const leagues = await api("/api/leagues");
  const sel = $("#sim-league");
  sel.innerHTML = leagues.map((l) => `<option value="${esc(l.code)}">${esc(l.name)}</option>`).join("");
  sel.value = leagues.some((l) => l.code === "E0") ? "E0" : leagues[0].code;
  const loadTeams = async () => {
    $("#sim-home").innerHTML = $("#sim-away").innerHTML = "<option>Cargando…</option>";
    const teams = await api(`/api/teams/${sel.value}`);
    const opts = teams.map((t) => `<option>${esc(t)}</option>`).join("");
    $("#sim-home").innerHTML = opts; $("#sim-away").innerHTML = opts;
    if (teams.length > 1) $("#sim-away").selectedIndex = 1;
  };
  sel.addEventListener("change", loadTeams);
  await loadTeams();
  $("#sim-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector("button"); btn.disabled = true;
    const odds = ["#sim-o1", "#sim-o2", "#sim-o3"].map((s) => parseFloat($(s).value));
    const body = { league: sel.value, home: $("#sim-home").value, away: $("#sim-away").value,
      odds: odds.every((o) => o > 1) ? odds : null };
    try {
      if (body.home === body.away) throw new Error("Elige dos equipos distintos.");
      renderSimResult(await api("/api/predict", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));
    } catch (err) {
      $("#sim-out").innerHTML = `<div class="callout warn">${esc(err.message)}</div>`;
    } finally { btn.disabled = false; }
  });
}
function renderSimResult(r) {
  const p = r.p_official;
  const conf = { alta: "good", media: "warn", baja: "bad" }[r.confidence.level];
  let betting = "";
  if (r.betting) {
    const b = r.betting, rec = r.recommendation;
    betting = `<div class="card"><h2>Frente a las cuotas</h2><p class="sub">Margen de la casa: ${pct(b.margin, 1)}. Umbral de valor de esta liga: ${signed(b.min_ev, 0)}, solo cuotas ≤ 4,0.</p>
      <div class="table-wrap"><table><thead><tr><th></th><th class="r">Cuota</th><th class="r">Mercado sin margen</th><th class="r">Modelo</th><th class="r">Oficial</th><th class="r">Valor (EV)</th></tr></thead>
      <tbody>${SEL.map((n, i) => `<tr><td>${n}</td><td class="r">${num(b.odds[i])}</td><td class="r">${pct(b.p_market[i], 1)}</td><td class="r">${pct(r.p_model[i], 1)}</td>
        <td class="r"><b>${pct(p[i], 1)}</b></td><td class="r">${signed(b.ev[i])}</td></tr>`).join("")}</tbody></table></div>
      <div class="reco" style="margin-top:12px">${rec.bet ? `<span class="pill warn">Valor marginal</span> ${SEL[rec.sel]} a ${num(rec.odds)} (EV ${signed(rec.ev)}). Sin ventaja demostrada: solo como experimento.`
        : `<span class="pill">No apostar</span> ${esc(rec.text)}`}</div></div>`;
  }
  const ou = Object.entries(r.over_under).filter(([k]) => ["1.5", "2.5", "3.5"].includes(k));
  $("#sim-out").innerHTML = `<div class="stack">
    <div class="card match">
      <div class="meta"><span>${esc(r.league_name)}</span><span class="pill ${SOURCE_PILL[r.source]}">${esc(r.source)}</span></div>
      <div class="teams"><div class="t">${esc(r.home)}</div><div class="vs">vs</div><div class="t r">${esc(r.away)}</div></div>
      ${probBar(p)}
      <div class="legend"><span><i style="background:var(--home)"></i>Local ${pct(p[0], 1)}</span><span><i style="background:var(--draw)"></i>Empate ${pct(p[1], 1)}</span><span><i style="background:var(--away)"></i>Visita ${pct(p[2], 1)}</span></div>
      <div class="kv">
        <div><span>Goles esperados</span><b class="num">${num(r.xg[0], 2)} – ${num(r.xg[1], 2)}</b></div>
        <div><span>Marcador más probable</span><b class="num">${esc(r.top_scores[0][0])}</b></div>
        <div><span>Ambos marcan</span><b class="num">${pct(r.btts)}</b></div>
        <div><span>Confianza del modelo</span><b><span class="pill ${conf}">${esc(r.confidence.level)}</span></b></div>
      </div>
    </div>
    <div class="grid g2">
      <div class="card"><h2>Marcadores más probables</h2><p class="sub">Del modelo de goles (Dixon-Coles).</p>
        <table><tbody>${r.top_scores.map(([s, q]) => `<tr><td><b>${esc(s)}</b></td><td style="width:60%"><span class="mini" style="width:${Math.round(q / r.top_scores[0][1] * 100)}%;background:var(--official)"></span></td><td class="r">${pct(q, 1)}</td></tr>`).join("")}</tbody></table></div>
      <div class="card"><h2>Goles totales</h2><p class="sub">Probabilidad de más / menos goles en el partido.</p>
        <table><thead><tr><th>Línea</th><th class="r">Más de</th><th class="r">Menos de</th></tr></thead>
        <tbody>${ou.map(([k, v]) => `<tr><td>${k.replace(".", ",")} goles</td><td class="r">${pct(v, 1)}</td><td class="r">${pct(1 - v, 1)}</td></tr>`).join("")}</tbody></table>
        <p class="sub" style="margin:12px 0 0">Confianza "${esc(r.confidence.level)}": ${r.confidence.min_recent_matches} partidos recientes del equipo con menos datos; los dos submodelos difieren en hasta ${pct(r.confidence.elo_dc_max_diff, 1)}.</p></div>
    </div>
    ${betting}
    <div class="card"><h2>Opciones para combinar</h2>
      <p class="sub">Agrega selecciones con <b>+</b>; quedan en tu boleto de la pestaña <a href="#combinadas">Combinadas</a>${'<span data-ticket-count></span>'}.</p>
      <div class="stack">${suggestionsBlock(r)}${optionsTable(r)}</div></div>
  </div>`;
  syncAddButtons();
}

// combos.js se carga después de este archivo: se enruta cuando ambos están listos.
window.addEventListener("DOMContentLoaded", route);
