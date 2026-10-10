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

/* ---------- escudos y logos ---------- */
// Logo servido por /logo (caché local de API-Football). Si no existe, iniciales con un color propio del equipo.
function initials(name) {
  const w = String(name || "?").replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter((x) => x.length > 1 || /\d/.test(x));
  return ((w[0] || "?")[0] + (w.length > 1 ? w[w.length - 1][0] : (w[0] || "").slice(1, 2))).toUpperCase();
}
function hueOf(name) {
  let h = 0;
  for (const ch of String(name)) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}
function logoFallback(img) {
  const s = document.createElement("span");
  s.className = img.className + " fb";
  s.textContent = img.dataset.ini || "";
  s.style.setProperty("--h", img.dataset.h || "210");
  if (!img.dataset.ini) s.style.display = "none";            // logo de liga sin respaldo: se oculta
  img.replaceWith(s);
}
function teamLogo(id, name, size = 22) {
  const ini = initials(name), h = hueOf(name);
  if (!id) return `<span class="tlogo fb" style="--h:${h};width:${size}px;height:${size}px">${esc(ini)}</span>`;
  return `<img class="tlogo" src="/logo/team/${id}" alt="" width="${size}" height="${size}" loading="lazy"
    data-ini="${esc(ini)}" data-h="${h}" style="width:${size}px;height:${size}px" onerror="logoFallback(this)">`;
}
function leagueLogo(code, size = 16) {
  if (!code) return "";
  return `<img class="llogo" src="/logo/league/${encodeURIComponent(code)}" alt="" width="${size}" height="${size}"
    loading="lazy" style="width:${size}px;height:${size}px" onerror="logoFallback(this)">`;
}
// Equipo con su escudo, en línea.
const teamTag = (id, name, size = 20) => `<span class="team">${teamLogo(id, name, size)}<span>${esc(name)}</span></span>`;
const matchTag = (o, size = 20) => `${teamTag(o.home_id, o.home, size)} <span class="vs-s">vs</span> ${teamTag(o.away_id, o.away, size)}`;
// Fila grande local – visita para tarjetas.
const teamsRow = (o) => `<div class="teams"><div class="t">${teamLogo(o.home_id, o.home, 34)}<span>${esc(o.home)}</span></div>
  <div class="vs">vs</div><div class="t r"><span>${esc(o.away)}</span>${teamLogo(o.away_id, o.away, 34)}</div></div>`;

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
// Oscuro por defecto; el claro solo si el usuario lo eligió (queda guardado). index.html lo aplica antes de pintar.
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("theme", t); } catch (e) { /* sin storage */ }
  redrawCharts();
}
$("#theme").addEventListener("click", () => {
  setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
});

/* ---------- navegación ---------- */
const views = { inicio: renderHome, partidos: renderMatches, combinadas: () => renderCombos(), resultados: renderTracking,
  rendimiento: renderBacktest, simulador: renderSimulator, "como-funciona": () => {} };
const rendered = new Set();
function route() {
  const id = (location.hash || "#inicio").slice(1);
  const key = id in views ? id : "inicio";             // "#sugeridas" (enlaces antiguos) cae en el panel
  document.querySelectorAll("section.view").forEach((s) => s.classList.toggle("active", s.id === "v-" + key));
  document.querySelectorAll(".navlink").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + key));
  const link = document.querySelector(`#nav a[href="#${key}"]`);
  if (link) { $("#page-title").textContent = link.dataset.title; document.title = `${link.dataset.title} · Futbol ML`; }
  if (!rendered.has(key) || key === "combinadas") {          // combinadas se redibuja: depende del boleto
    rendered.add(key);
    Promise.resolve(views[key]()).catch((e) => showError("v-" + key, e));
  }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
/* ---------- esqueletos de carga y estados vacíos ---------- */
// Siluetas de lo que va a aparecer (filas de partido, tarjetas, tablas) mientras responde la API.
const sk = (cls, style = "") => `<span class="skeleton ${cls}" ${style ? `style="${style}"` : ""}></span>`;
const SKELETONS = {
  kpi: () => `<div class="card skeleton-card" aria-hidden="true">${sk("skeleton-text", "width:55%")}
    ${sk("skeleton-num")}${sk("skeleton-text", "width:75%")}</div>`,
  rows: () => `<div class="sk-row">${sk("skeleton-text", "width:38px")}<div class="sk-teams">
    <div>${sk("skeleton-circle")}${sk("skeleton-text", "width:60%")}</div><div>${sk("skeleton-circle")}${sk("skeleton-text", "width:48%")}</div></div>
    ${sk("skeleton-cell")}${sk("skeleton-cell")}${sk("skeleton-cell")}${sk("skeleton-text sk-best")}</div>`,
  semrows: () => `<div class="sk-row sk-sem"><div class="sk-teams"><div>${sk("skeleton-circle")}${sk("skeleton-text", "width:70%")}</div>
    ${sk("skeleton-text", "width:45%")}</div>${Array(6).fill(sk("skeleton-cell")).join("")}${sk("skeleton-text sk-best")}</div>`,
  cards: () => `<div class="card skeleton-card" aria-hidden="true"><div class="sk-split">${sk("skeleton-text", "width:34%")}${sk("skeleton-text", "width:22%")}</div>
    <div class="sk-split"><div class="sk-team">${sk("skeleton-circle lg")}${sk("skeleton-text", "width:90px")}</div>
    <div class="sk-team">${sk("skeleton-text", "width:90px")}${sk("skeleton-circle lg")}</div></div>${sk("skeleton-bar")}</div>`,
  table: () => `<div class="sk-line">${sk("skeleton-text", "width:22%")}${sk("skeleton-text", "width:38%")}${sk("skeleton-text", "width:14%")}</div>`,
  lines: () => sk("skeleton-text", "width:85%;margin:6px 0"),
};
function skeleton(kind, n) {
  const one = SKELETONS[kind];
  const body = Array.from({ length: n }, one).join("");
  if (kind === "rows") return `<div class="lg-block skel-wrap" aria-busy="true"><div class="lg-head">${sk("skeleton-circle")}${sk("skeleton-text", "width:140px")}</div>${body}</div>`;
  if (kind === "kpi" || kind === "cards") return body;
  return `<div class="skel-wrap" aria-busy="true">${body}</div>`;
}
function paintSkeletons(root = document) {
  root.querySelectorAll("[data-skel]").forEach((el) => {
    const [kind, n] = el.dataset.skel.split(":");
    el.innerHTML = skeleton(kind, Number(n) || 3);
  });
}
const EMPTY_ICONS = {
  calendar: '<rect x="3" y="4.5" width="18" height="16" rx="3"/><path d="M8 2.5v4M16 2.5v4M3 10h18"/><path d="m9.5 14.5 5 4M14.5 14.5l-5 4"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/><path d="M8.5 11h5"/>',
  inbox: '<path d="M3 13.5 5.5 5h13L21 13.5V19a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 19z"/><path d="M3 13.5h5l1.5 2.5h5l1.5-2.5h5"/>',
};
// Estado vacío: ícono, mensaje y, si se indica, un botón de acción (p. ej. restablecer filtros).
function emptyState({ icon = "calendar", title, text = "", action = "" } = {}) {
  return `<div class="empty-state"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${EMPTY_ICONS[icon]}</svg>
    <b>${title}</b>${text ? `<p>${text}</p>` : ""}${action ? `<button type="button" class="empty-action">${action}</button>` : ""}</div>`;
}
// Lista filtrada sin resultados: si hay filtros activos, ofrece volver a ver todos los partidos.
function emptyMatches(box, filtered, reset, sel = null, catalog = []) {
  const league = sel && sel.type === "league" ? sel : null;
  const canSimulate = league && (catalog.find((c) => c.code === league.code) || {}).model;
  box.innerHTML = filtered
    ? emptyState({ icon: "search", title: league ? `${esc(league.name)} no tiene partidos para este filtro` : "Sin partidos para este filtro",
      text: canSimulate ? "Puedes simular cualquier partido de esta liga o volver a ver todos." : "Prueba con otra liga, equipo o día.",
      action: "Ver todos los partidos" })
    : emptyState({ title: "No hay partidos programados en los próximos 3 días",
      text: "Puede ser fecha FIFA. La tarea diaria agrega partidos y cuotas a medida que se publican." });
  const b = box.querySelector(".empty-action");
  if (b) b.onclick = reset;
  if (canSimulate && b) {
    b.insertAdjacentHTML("beforebegin", `<button type="button" class="empty-action alt">Simular un partido de ${esc(league.name)}</button>`);
    box.querySelector(".empty-action.alt").onclick = () => goSimulate(league.code);
  }
}
// Abre el simulador con una liga elegida (si tiene modelo; si no, queda la liga por defecto).
let pendingSimLeague = null;
function goSimulate(code) {
  pendingSimLeague = code;
  const sel = $("#sim-league");
  if (sel && [...sel.options].some((o) => o.value === code)) {
    sel.value = code; sel.dispatchEvent(new Event("change")); pendingSimLeague = null;
  }
  location.hash = "#simulador";
}
const isFiltered = (sel, date) => (sel && sel.type !== "all") || (date && date.type !== "all");

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
const FONT_BODY = '"Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", ui-monospace, Consolas, monospace';
const FONT_DISPLAY = '"Plus Jakarta Sans", "Inter", system-ui, sans-serif';
if (window.Chart) {                       // gráficos con la tipografía del sitio y tooltips flotantes con sombra
  Chart.defaults.font.family = FONT_BODY;
  Chart.defaults.font.size = 11.5;
  Chart.register({
    id: "tooltipShadow",
    beforeTooltipDraw: (ch) => { const c = ch.ctx; c.save(); c.shadowColor = "rgba(2, 6, 23, .45)"; c.shadowBlur = 18; c.shadowOffsetY = 6; },
    afterTooltipDraw: (ch) => ch.ctx.restore(),
  });
}
// Color de un token con transparencia (los tokens son #rrggbb o rgb[a]()).
function rgba(color, a) {
  const c = color.trim();
  if (c.startsWith("#")) {
    const h = c.length === 4 ? [...c.slice(1)].map((x) => x + x).join("") : c.slice(1, 7);
    return `rgba(${parseInt(h.slice(0, 2), 16)}, ${parseInt(h.slice(2, 4), 16)}, ${parseInt(h.slice(4, 6), 16)}, ${a})`;
  }
  const n = c.match(/[\d.]+/g) || [0, 0, 0];
  return `rgba(${n[0]}, ${n[1]}, ${n[2]}, ${a})`;
}
// Relleno degradado vertical bajo una curva, desde su color hasta transparente (se calcula con el área ya medida).
function areaGradient(color, top = 0.30) {
  return (ctx) => {
    const { chart: ch } = ctx;
    if (!ch.chartArea) return rgba(color, top / 2);
    const g = ch.ctx.createLinearGradient(0, ch.chartArea.top, 0, ch.chartArea.bottom);
    g.addColorStop(0, rgba(color, top));
    g.addColorStop(1, rgba(color, 0));
    return g;
  };
}
// Curva de bankroll / unidades: suave, sin puntos salvo al pasar el cursor, con área sombreada hasta `base`.
const curveSet = (label, data, color, base = null) => ({
  label, data, showLine: true, borderColor: color, backgroundColor: base == null ? color : areaGradient(color),
  fill: base == null ? false : { target: { value: base } }, borderWidth: 2.2, tension: 0.3,
  pointRadius: 0, pointHoverRadius: 5, pointHoverBorderWidth: 3, pointHoverBorderColor: css("--surface"), pointHoverBackgroundColor: color,
});
// Línea de equilibrio (punto de partida o cero), punteada y bien visible.
const breakEven = (label, x0, x1, y) => ({ label, data: [{ x: x0, y }, { x: x1, y }], showLine: true, borderColor: css("--text-2"),
  borderWidth: 1.3, borderDash: [5, 5], pointRadius: 0, pointHoverRadius: 0, fill: false });
// Calibración: diagonal ideal en guiones y puntos con halo al pasar el cursor.
const diagonal = () => ({ label: "Calibración perfecta", data: [{ x: 0, y: 0 }, { x: 100, y: 100 }], showLine: true,
  borderColor: css("--muted"), borderWidth: 1.2, borderDash: [6, 6], pointRadius: 0, pointHoverRadius: 0 });
const calibStyle = (color) => ({ showLine: true, borderColor: color, backgroundColor: color, borderWidth: 2, tension: 0.2,
  pointRadius: 4.5, pointBorderColor: css("--surface"), pointBorderWidth: 2,
  pointHoverRadius: 8, pointHoverBorderWidth: 8, pointHoverBorderColor: rgba(color, 0.28), pointHoverBackgroundColor: color });
function baseOptions(extra = {}) {
  const grid = css("--grid"), text = css("--text-2");
  return {
    responsive: true, maintainAspectRatio: false, animation: { duration: 400, easing: "easeOutQuart" },
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { position: "top", align: "start", labels: { color: text, boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 3,
        font: { size: 12 }, filter: (it) => !/^(Calibración perfecta|Punto de partida|Inicio|Equilibrio)$/.test(it.text),
        // las series con área degradada usan el color de su línea en la leyenda
        generateLabels: (ch) => Chart.defaults.plugins.legend.labels.generateLabels(ch)
          .map((l) => (typeof l.fillStyle === "string" ? l : { ...l, fillStyle: l.strokeStyle })) } },
      // tooltip oscuro tipo terminal en ambos temas: cifras en monoespaciada
      tooltip: { backgroundColor: "#111726", titleColor: "#f1f5fb", bodyColor: "#c9d3e3", footerColor: "#8b97ab",
        borderColor: "rgba(255, 255, 255, .10)", borderWidth: 1, padding: 12, cornerRadius: 10, boxPadding: 5, caretSize: 6,
        usePointStyle: true, titleFont: { family: FONT_DISPLAY, weight: "700", size: 12.5 },
        bodyFont: { family: FONT_MONO, size: 12 }, footerFont: { family: FONT_MONO, size: 11, weight: "500" } },
    },
    scales: {
      x: { grid: { color: grid, drawTicks: false }, border: { display: false }, ticks: { color: text, font: { family: FONT_MONO, size: 11 }, padding: 6 } },
      y: { grid: { color: grid, drawTicks: false }, border: { display: false }, ticks: { color: text, font: { family: FONT_MONO, size: 11 }, padding: 6 } },
    },
    ...extra,
  };
}

/* ---------- componentes ---------- */
// Barra 1X2 de la probabilidad oficial. Con `pm` (mercado sin margen) agrega debajo una barra fina del mercado con
// la misma escala: si los cortes no coinciden, el sistema y el mercado ven distinto el partido.
function probBar(p, pm = null) {
  if (!p) return `<div class="probbar"><div style="flex:1;background:var(--surface-2);color:var(--muted)">sin datos</div></div>`;
  const cls = ["h", "d", "a"];
  const bar = `<div class="probbar" role="img" aria-label="Local ${pct(p[0])}, empate ${pct(p[1])}, visita ${pct(p[2])}">${
    p.map((x, i) => `<div class="${cls[i]}" style="flex:${x}" title="${SEL[i]}: ${pct(x, 1)}">${x >= 0.12 ? pct(x) : ""}</div>`).join("")}</div>`;
  if (!pm) return bar;
  const mk = `<div class="mkbar" role="img" aria-label="Mercado: local ${pct(pm[0])}, empate ${pct(pm[1])}, visita ${pct(pm[2])}">${
    pm.map((x, i) => `<div class="${cls[i]}" style="flex:${x}" title="Mercado · ${SEL[i]}: ${pct(x, 1)}"></div>`).join("")}</div>`;
  return `<div class="pb-pair"><span class="pb-lab">Sistema</span>${bar}<span class="pb-lab">Mercado</span>${mk}</div>`;
}
// Insignia de valor: solo para selecciones que el profesional apostaría (precio justo de Pinnacle).
const evBadge = (o) => (o && o.verdict && o.verdict.level === "green" && o.ev != null
  ? `<span class="ev-badge" title="${esc(o.verdict.reason)}">VALOR ${signed(o.ev)}</span>` : "");
function miniBar(p) {
  const c = ["var(--home)", "var(--draw)", "var(--away)"];
  return `<span class="mini" title="L ${pct(p[0])} · E ${pct(p[1])} · V ${pct(p[2])}">${p.map((x, i) => `<i style="flex:${x};background:${c[i]}"></i>`).join("")}</span>`;
}
function stat(label, value, hint = "") {
  return `<div class="card stat"><div class="label">${label}</div><div class="value num">${value}</div>${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
}
const SOURCE_PILL = { "modelo + mercado": "good", modelo: "", mercado: "warn", "sin datos": "", error: "bad" };

/* ---------- calculadora de apuesta ---------- */
const clp = (x) => (x == null || isNaN(x) ? "–" : (x < 0 ? "−$" : "$") + Math.round(Math.abs(x)).toLocaleString("es-CL"));
function getStake() {
  try { return Number(localStorage.getItem("stake")) || 5000; } catch (e) { return 5000; }
}
function setStake(v) {
  try { localStorage.setItem("stake", String(v)); } catch (e) { /* sin storage */ }
}
// Resultado de apostar `stake` a `odds` con probabilidad `p` de acertar (según el sistema).
function payout(stake, odds, p) {
  const ret = stake * odds;
  return { ret, net: ret - stake, lose: -stake, expected: p == null ? null : stake * (p * odds - 1), p };
}
/* ---------- semáforo ---------- */
function vchip(v, text) {
  v = v || { level: "none", label: "Sin cuota", reason: "" };
  return `<span class="vchip ${v.level}" title="${esc(v.reason)}"><b>${esc(v.label)}</b>${text ? ` ${text}` : ""}</span>`;
}
function vcell(op) {
  if (!op) return `<div class="vcell none">–</div>`;
  const v = op.verdict || { level: "none", label: "Sin cuota", reason: "" };
  return `<div class="vcell ${v.level}" title="${esc(op.label)}: ${esc(v.reason)}"><b>${pct(op.p)}</b>
    <span>${op.odds ? num(op.odds) : "sin cuota"}</span><small>${esc(v.label)}</small></div>`;
}
const SEM_COLS = [["1", "Local"], ["X", "Empate"], ["2", "Visita"], ["O2.5", "Más 2,5"], ["U2.5", "Menos 2,5"], ["BTTS_Y", "Ambos marcan"]];
const RANK = { green: 3, yellow: 2, none: 1, red: 0 };
let semSel = { type: "all" }, semDate = { type: "all" };
async function renderSemaphore() {
  const [list, catalog] = await Promise.all([api("/api/upcoming"), leagueCatalog()]);
  const draw = () => {
    const shown = list.filter((m) => leagueSelMatch(semSel, m, catalog) && dateSelMatch(semDate, m.kickoff));
    if (!shown.length) return emptyMatches($("#semaforo"), isFiltered(semSel, semDate), reset, semSel, catalog);
    $("#semaforo").innerHTML = `<table class="sem"><thead><tr><th>Partido</th>${SEM_COLS.map(([, n]) => `<th style="text-align:center">${n}</th>`).join("")}
      <th>Mejor opción</th></tr></thead><tbody>${shown.map(semRow).join("")}</tbody></table>`;
  };
  const mount = () => {
    mountLeaguePicker($("#sem-filter"), { value: semSel, onChange: (s) => { semSel = s; draw(); } });
    mountDateFilter($("#sem-date"), { list, value: semDate, onChange: (s) => { semDate = s; draw(); } });
  };
  const reset = () => { semSel = { type: "all" }; semDate = { type: "all" }; mount(); draw(); };
  mount();
  draw();
  return list;
}
function bestOption(m) {
  return (m.options || []).filter((o) => o.odds && !o.estimated && o.verdict)
    .sort((a, b) => (RANK[b.verdict.level] - RANK[a.verdict.level]) || ((b.ev ?? -9) - (a.ev ?? -9)))[0];
}
function semRow(m) {
  const ops = Object.fromEntries((m.options || []).map((o) => [o.key, o]));
  const best = bestOption(m);
  return `<tr><td class="m" onclick="goToCombos('${esc(m.ref)}')"><div class="mt">${matchTag(m, 22)}</div>
    <div style="color:var(--muted);font-size:12px">${leagueLogo(m.league, 13)} ${esc(m.league_name)} · ${fmtDate(m.kickoff)}${m.stale ? " · ⚠ datos atrasados" : ""}</div></td>
    ${SEM_COLS.map(([k]) => `<td>${vcell(ops[k])}</td>`).join("")}
    <td>${best ? `${vchip(best.verdict)}<div style="font-size:12.5px;margin-top:4px">${esc(best.label)} a ${num(best.odds)}</div>`
      : '<span style="color:var(--muted);font-size:12.5px">sin cuotas aún</span>'}</td></tr>`;
}

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

  // Cada sección se dibuja por su cuenta en cuanto llega su dato; los indicadores esperan a ambos.
  renderSemaphore().catch((e) => showError("v-inicio", e));
  const [sug, rel] = await Promise.all([renderSuggestions(), renderReliable()]);
  const L = sug.ledger || {}, R = rel.record || {};
  $("#home-tiles").innerHTML = [
    `<div class="card stat kpi-good"><div class="label">Apuestas con valor hoy</div>
      <div class="value num">${sug.singles.length}</div><div class="hint">en ${sug.n_matches_sharp} partidos con precio de Pinnacle</div></div>`,
    stat("Pronósticos fiables hoy", rel.today.length, `selecciones con ${pct(rel.min_p)} o más`),
    stat("Precisión en vivo", R.n ? pct(R.hit, 1) : "–", R.n ? `esperaba ${pct(R.expected, 1)} · ${R.n} pronósticos` : `${R.pending || 0} pronósticos esperando resultado`),
    stat("Cartera en papel", L.settled ? signed(L.yield) : `${L.open || 0} abiertas`,
      L.clv != null ? `CLV ${signed(L.clv)} · ${pct(L.clv_pos)} sobre el cierre` : L.settled ? `${L.won} ganadas de ${L.settled}` : "se mide al terminar cada partido"),
  ].join("");

  chart("ch-confidence", () => ({
    type: "bar",
    data: {
      labels: o.confidence.map((c) => c.range),
      datasets: [
        { label: "Probabilidad que dio el sistema", data: o.confidence.map((c) => c.pred * 100), backgroundColor: css("--official"), borderRadius: 6, maxBarThickness: 24, borderSkipped: "start" },
        { label: "Acierto real", data: o.confidence.map((c) => c.hit * 100), backgroundColor: css("--model"), borderRadius: 6, maxBarThickness: 24, borderSkipped: "start" },
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
let matchSel = { type: "all" }, matchDate = { type: "all" };
async function renderMatches() {
  const [list, catalog] = await Promise.all([api("/api/upcoming"), leagueCatalog()]);
  const byRef = Object.fromEntries(list.map((m) => [m.ref, m]));
  const draw = () => {
    const shown = list.filter((m) => leagueSelMatch(matchSel, m, catalog) && dateSelMatch(matchDate, m.kickoff));
    if (chips) chips.sync();
    if (!shown.length) return emptyMatches($("#matches"), isFiltered(matchSel, matchDate), reset, matchSel, catalog);
    $("#matches").innerHTML = matchGroups(shown);
  };
  let chips = null;
  const mount = async () => {
    const picker = await mountLeaguePicker($("#league-filter"), { value: matchSel, onChange: (s) => { matchSel = s; draw(); } });
    mountDateFilter($("#match-date"), { list, value: matchDate, onChange: (s) => { matchDate = s; draw(); } });
    chips = mountQuickChips($("#match-chips"), { list, catalog, picker, getSel: () => matchSel,
      onPick: (s) => { matchSel = s; draw(); } });
  };
  const reset = () => { matchSel = { type: "all" }; matchDate = { type: "all" }; mount(); draw(); };
  mount();
  $("#matches").onclick = (e) => {
    if (e.target.closest("button, a, .mdetail")) return;
    const row = e.target.closest(".mrow"); if (!row) return;
    const next = row.nextElementSibling;
    if (next && next.classList.contains("mdetail")) { next.remove(); row.classList.remove("open"); return; }
    row.classList.add("open");
    row.insertAdjacentHTML("afterend", `<div class="mdetail">${matchCard(byRef[row.dataset.ref])}</div>`);
  };
  draw();
}
function matchGroups(list) {
  const groups = new Map();
  list.forEach((m) => { if (!groups.has(m.league)) groups.set(m.league, []); groups.get(m.league).push(m); });
  return [...groups.values()].map((ms) => `<div class="lg-block">
    <div class="lg-head">${leagueLogo(ms[0].league, 20)}<span>${esc(ms[0].league_name)}</span>
      <span class="cnt">${ms.length} ${ms.length === 1 ? "partido" : "partidos"}</span></div>
    <div class="lg-cols"><span>Hora</span><span>Partido</span><span>1</span><span>X</span><span>2</span><span>Mejor opción</span><span></span></div>
    ${ms.map(matchRow).join("")}</div>`).join("");
}
function matchRow(m) {
  const p = m.p_official;
  const ops = Object.fromEntries((m.options || []).map((o) => [o.key, o]));
  const fav = p ? p.indexOf(Math.max(...p)) : -1;
  const d = new Date(m.kickoff);
  const time = new Intl.DateTimeFormat("es-CL", { hour: "2-digit", minute: "2-digit", hour12: false }).format(d);
  const day = new Intl.DateTimeFormat("es-CL", { weekday: "short", day: "numeric" }).format(d);
  const pm = m.p_market;
  const cell = (k, i, color) => {
    if (!p) return `<div class="pcell"><b>–</b><span>sin datos</span></div>`;
    const o = ops[k], v = o && o.verdict;
    const tip = [v ? `${v.label}: ${v.reason}` : "", pm ? `Mercado: ${pct(pm[i])}` : ""].filter(Boolean).join(" · ");
    return `<div class="pcell ${i === fav ? "top" : ""} ${v && v.level === "green" ? "value" : ""}"
      style="--w:${(p[i] * 100).toFixed(0)}%;--c:var(${color})"
      title="${esc(tip)}"><b>${pct(p[i])}</b><span>${o && o.odds ? num(o.odds) : "–"}</span></div>`;
  };
  const best = bestOption(m);
  const tag = (id, name, isFav) => `<span class="team ${isFav ? "fav" : ""}">${teamLogo(id, name, 20)}<span>${esc(name)}</span></span>`;
  return `<div class="mrow" data-ref="${esc(m.ref)}">
    <div class="time"><b>${time}</b><span>${esc(day)}</span></div>
    <div class="tm">${tag(m.home_id, m.home, fav === 0)}${tag(m.away_id, m.away, fav === 2)}</div>
    ${cell("1", 0, "--home")}${cell("X", 1, "--draw")}${cell("2", 2, "--away")}
    <div class="best">${best ? `${evBadge(best) || vchip(best.verdict)}<span>${esc(best.label)} · ${num(best.odds)}</span>` : `<span>${m.stale ? "datos atrasados" : "sin cuotas aún"}</span>`}</div>
    <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>
  </div>`;
}
function matchCard(m) {
  const p = m.p_official;
  const fav = p ? p.indexOf(Math.max(...p)) : null;
  const r = m.recommendation || {};
  // Recomendación = la mejor opción del partido según el semáforo (misma regla que el panel).
  const best = bestOption(m);
  const reco = best
    ? `${vchip(best.verdict)} <span>Mejor opción: <b style="color:var(--text)">${esc(best.label)}</b> a ${num(best.odds)} · ${esc(best.verdict.reason)}</span>`
    : `${vchip({ level: "none", label: "Sin cuota", reason: "" })} <span>${esc(r.text || "Aún no hay cuotas para evaluar el retorno.")}</span>`;
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
  let form = "";
  if (m.form && m.form.form_h != null) {
    const f = m.form;
    form = `<div class="compare">
      <div class="odds-row"><span>Forma (últ. 5)</span><span>${num(f.form_h, 1)} pts</span><span></span><span>${num(f.form_a, 1)} pts</span></div>
      <div class="odds-row"><span>Goles (últ. 10)</span><span>${num(f.gf_h, 1)}–${num(f.ga_h, 1)}</span><span></span><span>${num(f.gf_a, 1)}–${num(f.ga_a, 1)}</span></div>
      ${f.h2h_n ? `<div style="color:var(--muted)">Últimos ${f.h2h_n} enfrentamientos: ${esc(m.home)} sumó ${num(f.h2h_pts, 1)} pts por partido</div>` : ""}</div>`;
  }
  let mlOnly = "";
  if (m.p_model && !m.p_market && m.model_name === "ML historial") {
    mlOnly = `<div class="reco"><span class="pill">pronóstico ML</span> sin cuotas aún: probabilidades del modelo entrenado con el historial de los equipos</div>`;
  }
  let compare = "";
  if (m.p_model && m.p_market) {
    compare = `<div class="compare">
      <div class="row"><span></span><span>Local</span><span>Empate</span><span>Visita</span></div>
      <div class="row"><span>${esc(m.model_name === "ML historial" ? "ML" : "Modelo")}</span>${m.p_model.map((x) => `<span class="num">${pct(x)}</span>`).join("")}</div>
      <div class="row"><span>Mercado</span>${m.p_market.map((x) => `<span class="num">${pct(x)}</span>`).join("")}</div></div>`;
  }
  return `<article class="card match">
    <div class="meta"><span class="lg">${leagueLogo(m.league, 16)}${esc(m.league_name)}</span><span>${fmtDate(m.kickoff)}</span></div>
    ${teamsRow(m)}
    <div>${probBar(p, m.p_market)}</div>
    <div class="reco"><span class="pill ${SOURCE_PILL[m.source] ?? ""}">${esc(m.source)}</span>
      ${fav != null ? `<span>Más probable: <b style="color:var(--text)">${fav === 1 ? "empate" : fav === 0 ? esc(m.home) : esc(m.away)}</b></span>` : ""}</div>
    ${m.options && m.options.length ? `<div class="sem-legend">${["1", "X", "2"].map((k) => {
      const op = m.options.find((x) => x.key === k);
      return op ? vchip(op.verdict, `${k === "1" ? "Local" : k === "X" ? "Empate" : "Visita"} ${pct(op.p)}`) : "";
    }).join("")}</div>` : ""}
    ${oddsHtml}${extra}${form}${compare}${mlOnly}
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
      <td>${fmtDate(m.kickoff)}</td><td title="${esc(m.league_name || m.league)}">${leagueLogo(m.league, 18) || esc(m.league)}</td><td>${matchTag(m, 18)}</td>
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
  renderRuleHistory().catch((e) => showError("v-rendimiento", e));
  renderML().catch((e) => showError("v-rendimiento", e));
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
        diagonal(),
        { label: "Probabilidad oficial", data: pts("official"), ...calibStyle(css("--official")) },
        { label: "Modelo solo", data: pts("model"), ...calibStyle(css("--model")) },
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
        breakEven("Equilibrio", 0, 100, 0),
        curveSet(`Modelo solo (${bm.n.toLocaleString("es-CL")} apuestas)`, toPts(bm), css("--model")),
        curveSet(`v2: modelo + mercado, cuota ≤ 4 (${bo.n} apuestas)`, toPts(bo), css("--official"), 0),
      ] },
      options: baseOptions({
        interaction: { mode: "nearest", intersect: false, axis: "x" },
        plugins: { ...baseOptions().plugins, tooltip: { ...baseOptions().plugins.tooltip,
          filter: (i) => i.datasetIndex > 0,
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
      backgroundColor: bm.buckets.map((b) => (b.yield < 0 ? css("--bad") : css("--ev-positive"))), borderRadius: 6, maxBarThickness: 24, borderSkipped: "start" }] },
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
    <tbody>${d.per_league.map((r) => `<tr><td><span class="team">${leagueLogo(r.code, 18)}<span>${esc(r.name)}</span></span> <span style="color:var(--muted)">${esc(r.code)}</span></td><td class="r">${r.n}</td>
      <td class="r">${pct(r.acc_model, 1)}</td><td class="r">${pct(r.acc_market, 1)}</td><td class="r">${pct(r.acc_official, 1)}</td>
      ${["ll_model", "ll_market", "ll_official"].map((k) => `<td class="r" ${r[k] === best(r) ? 'style="font-weight:650;color:var(--text)"' : 'style="color:var(--text-2)"'}>${num(r[k], 3)}</td>`).join("")}
      <td><span class="pill ${r.status.startsWith("pasó") ? "warn" : ""}" title="${esc(r.status)}">${r.status.startsWith("pasó") ? "en observación" : "sin ventaja"}</span></td></tr>`).join("")}</tbody></table>`;
}

/* ---------- MACHINE LEARNING (análisis 05) ---------- */
async function renderML() {
  const r = await api("/api/ml");
  if (!r || !r.x12) { $("#ml-block").innerHTML = `<div class="empty">Aún no hay modelos entrenados (python scripts/train_ml.py).</div>`; return; }
  const row = (label, x, best) => `<tr><td>${label}</td><td class="r" ${x.logloss === best ? 'style="font-weight:650;color:var(--text)"' : ""}>${num(x.logloss, 4)}</td><td class="r">${pct(x.acc, 1)}</td></tr>`;
  const tbl = (title, block, items) => {
    const best = Math.min(...items.map(([k]) => block[k].logloss));
    return `<div><h3 style="margin-bottom:8px">${title}</h3><table><thead><tr><th>Fuente</th><th class="r">Log loss</th><th class="r">Acierto</th></tr></thead>
      <tbody>${items.map(([k, l]) => row(l, block[k], best)).join("")}</tbody></table></div>`;
  };
  const b = r.bets.ml;
  $("#ml-block").innerHTML = `
    <div class="grid g3">
      ${tbl(`Resultado 1X2 (${r.x12.n.toLocaleString("es-CL")} partidos)`, r.x12, [["elo_dc", "Elo + Dixon-Coles"], ["ml", "ML historial"], ["mercado", "Mercado"], ["ml_mercado", "ML + mercado"]])}
      ${tbl(`Más/menos de 2,5 (${r.over25.n.toLocaleString("es-CL")})`, r.over25, [["dixon_coles", "Dixon-Coles"], ["ml", "ML historial"], ["mercado", "Mercado"], ["ml_mercado", "ML + mercado"]])}
      ${tbl("Ambos marcan", r.btts, [["frecuencia_historica", "Frecuencia histórica"], ["ml", "ML historial"]])}
    </div>
    <div class="stack" style="font-size:14px;color:var(--text-2);margin-top:16px">
      <p><b style="color:var(--text)">El ML mejora a los modelos anteriores, pero poco:</b> aprende de ${r.n_features} variables del historial de los equipos
        (forma, tiros, localía, temporada, rachas, descanso, enfrentamientos directos) con ${r.n_train.toLocaleString("es-CL")} partidos.</p>
      <p><b style="color:var(--text)">No alcanza al mercado:</b> al combinarlos, el ML recibe peso ${num(r.blend["1x2"][0], 2)} frente a
        ${num(r.blend["1x2"][1], 2)} del mercado. Lo que dice el historial público de los equipos ya está en las cuotas.</p>
      <p><b style="color:var(--text)">Apostar con el ML solo pierde:</b> ${b.n.toLocaleString("es-CL")} apuestas con la regla de sugerencias,
        ${signed(b.yield)} por unidad (IC95% ${signed(b.ci[0], 0)} a ${signed(b.ci[1], 0)}). Por eso las apuestas sugeridas siguen usando la probabilidad oficial.</p>
      <p>Para superar al mercado harían falta datos que el historial no tiene: alineaciones confirmadas, lesiones y cuotas tempranas.</p>
    </div>
    <div style="margin-top:12px"><h3 style="margin-bottom:6px">Variables que más pesan</h3>
      <p class="sub" style="margin-bottom:6px">${r.importance.slice(0, 8).map((x) => `<code>${esc(x.feature)}</code>`).join(" · ")}</p></div>`;
}

/* ---------- SIMULADOR ---------- */
async function renderSimulator() {
  $("#sim-stake").value = getStake();
  // El envío se registra primero (si no, un clic temprano recargaría la página) y el botón espera a los equipos.
  const submitBtn = $("#sim-form button");
  submitBtn.disabled = true;
  submitBtn.textContent = "Cargando equipos…";
  $("#sim-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector("button"); btn.disabled = true;
    const odds = ["#sim-o1", "#sim-o2", "#sim-o3"].map((s) => parseFloat($(s).value));
    const st = parseFloat($("#sim-stake").value);
    if (st > 0) setStake(st);
    const body = { league: sel.value, home: $("#sim-home").value, away: $("#sim-away").value,
      odds: odds.every((o) => o > 1) ? odds : null };
    try {
      if (body.home === body.away) throw new Error("Elige dos equipos distintos.");
      renderSimResult(await api("/api/predict", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));
    } catch (err) {
      $("#sim-out").innerHTML = `<div class="callout warn">${esc(err.message)}</div>`;
    } finally { btn.disabled = false; }
  });
  const leagues = await api("/api/leagues");
  const sel = $("#sim-league");
  sel.innerHTML = leagues.map((l) => `<option value="${esc(l.code)}">${esc(l.name)}</option>`).join("");
  sel.value = pendingSimLeague && leagues.some((l) => l.code === pendingSimLeague) ? pendingSimLeague
    : leagues.some((l) => l.code === "E0") ? "E0" : leagues[0].code;
  pendingSimLeague = null;
  const loadTeams = async () => {
    $("#sim-home").innerHTML = $("#sim-away").innerHTML = "<option>Cargando…</option>";
    const teams = await api(`/api/teams/${sel.value}`);
    const opts = teams.map((t) => `<option>${esc(t)}</option>`).join("");
    $("#sim-home").innerHTML = opts; $("#sim-away").innerHTML = opts;
    if (teams.length > 1) $("#sim-away").selectedIndex = 1;
  };
  sel.addEventListener("change", loadTeams);
  await loadTeams();
  submitBtn.disabled = false;
  submitBtn.textContent = "Calcular probabilidades";
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
  const simOdds = r.betting ? r.betting.odds : p.map((x) => 1 / x);
  const simulator = `<div class="card"><h2>Simula tu apuesta</h2>
      <p class="sub">${r.betting ? "Con las cuotas que ingresaste." : "Sin cuotas ingresadas se usa la cuota justa del sistema (ganancia esperada 0); ingresa las de tu casa para el cálculo real."}</p>
      <div class="filters"><label style="flex-direction:row;align-items:center;display:flex;gap:10px">Monto
        <input id="sim-stake2" type="number" min="1" step="any" value="${getStake()}" style="width:150px"></label></div>
      <div class="table-wrap" id="sim-payouts"></div></div>`;
  $("#sim-out").innerHTML = `<div class="stack">
    <div class="card match">
      <div class="meta"><span class="lg">${leagueLogo(r.league, 16)}${esc(r.league_name)}</span><span class="pill ${SOURCE_PILL[r.source]}">${esc(r.source)}</span></div>
      ${teamsRow(r)}
      ${probBar(p, r.betting ? r.betting.p_market : null)}
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
    ${simulator}
    ${betting}
    <div class="card"><h2>Opciones para combinar</h2>
      <p class="sub">Agrega selecciones con <b>+</b>; quedan en tu boleto de la pestaña <a href="#combinadas">Combinadas</a>${'<span data-ticket-count></span>'}.</p>
      <div class="stack">${suggestionsBlock(r)}${optionsTable(r)}</div></div>
  </div>`;
  syncAddButtons();
  const drawSim = () => {
    const st = parseFloat($("#sim-stake2").value) || 0;
    $("#sim-payouts").innerHTML = `<table><thead><tr><th>Apuesta</th><th class="r">Cuota</th><th class="r">Probabilidad</th>
      <th class="r">Si aciertas, recibes</th><th class="r">Ganancia neta</th><th class="r">Si fallas</th><th class="r">Ganancia esperada</th></tr></thead>
      <tbody>${SEL.map((n, i) => {
        const x = payout(st, simOdds[i], p[i]);
        return `<tr><td>${n}</td><td class="r">${num(simOdds[i])}</td><td class="r">${pct(p[i], 1)}</td><td class="r"><b>${clp(x.ret)}</b></td>
          <td class="r" style="color:var(--good)">+${clp(x.net)}</td><td class="r" style="color:var(--bad)">${clp(x.lose)}</td>
          <td class="r" style="color:${x.expected >= 0 ? "var(--good)" : "var(--bad)"}"><b>${x.expected >= 0 ? "+" : ""}${clp(x.expected)}</b></td></tr>`;
      }).join("")}</tbody></table>`;
  };
  $("#sim-stake2").oninput = (e) => { setStake(e.target.value); drawSim(); };
  drawSim();
}

/* ---------- barra lateral y superior ---------- */
async function initChrome() {
  $("#tb-date").textContent = new Intl.DateTimeFormat("es-CL", { weekday: "long", day: "numeric", month: "long" }).format(new Date());
  try {
    const o = await api("/api/overview");
    const el = $("#status-line");
    if (o.last_daily_run) {
      const h = (Date.now() - new Date(o.last_daily_run)) / 3.6e6;
      const ago = h < 1 ? `hace ${Math.max(1, Math.round(h * 60))} min` : h < 48 ? `hace ${Math.round(h)} h` : `hace ${Math.round(h / 24)} días`;
      el.classList.toggle("stale", h > 30);
      el.innerHTML = `<i class="dot"></i><span>Datos actualizados ${ago}<br>modelo ${esc(o.model_version)}</span>`;
    }
  } catch (e) { /* el estado es informativo */ }
}

// combos.js se carga después de este archivo: se enruta cuando ambos están listos.
window.addEventListener("DOMContentLoaded", () => { paintSkeletons(); route(); initChrome(); });
