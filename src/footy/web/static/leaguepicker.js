"use strict";
/* Buscador de ligas con sugerencias en vivo, filtros por continente y país, y navegación con teclado.
   Uso: mountLeaguePicker(contenedor, { value, onChange }). La selección es un objeto:
     { type: "all" } | { type: "league", code, name } | { type: "country", value } | { type: "continent", value }
   y leagueSelMatch(sel, partido) dice si un partido entra en la selección. */

const CONTINENTS = ["Europa", "Sudamérica", "Norteamérica", "Asia", "Selecciones"];
let leagueCatalogP = null;
function leagueCatalog() {
  if (!leagueCatalogP) leagueCatalogP = api("/api/league-catalog").catch(() => []);
  return leagueCatalogP;
}
const normTxt = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

// Puntaje de coincidencia (0 = no coincide). Prioriza: código exacto, nombre que empieza igual, palabra que empieza
// igual, nombre que contiene, país, continente y, al final, letras en orden (búsqueda difusa).
function leagueScore(lg, q) {
  if (!q) return 1;
  const name = normTxt(lg.name), country = normTxt(lg.country), cont = normTxt(lg.continent), code = normTxt(lg.code);
  let total = 0;
  for (const t of q.split(/\s+/).filter(Boolean)) {
    let s = 0;
    if (code === t) s = 120;
    else if (name.startsWith(t)) s = 100;
    else if (name.split(/[\s.-]+/).some((w) => w.startsWith(t))) s = 85;
    else if (name.includes(t)) s = 65;
    else if (country.startsWith(t)) s = 60;
    else if (country.includes(t)) s = 45;
    else if (cont.startsWith(t)) s = 35;
    else {
      let i = 0;                                           // difusa: las letras aparecen en orden
      for (const ch of name) if (ch === t[i]) i += 1;
      if (i === t.length) s = 15 + Math.round(10 * t.length / name.length);
    }
    if (!s) return 0;
    total += s;
  }
  return total;
}
function highlight(text, q) {
  const t = normTxt(text), tok = q.split(/\s+/).filter(Boolean).sort((a, b) => b.length - a.length)[0];
  const i = tok ? t.indexOf(tok) : -1;
  if (i < 0) return esc(text);
  return `${esc(text.slice(0, i))}<mark>${esc(text.slice(i, i + tok.length))}</mark>${esc(text.slice(i + tok.length))}`;
}
function leagueSelMatch(sel, m, catalog) {
  if (!sel || sel.type === "all") return true;
  if (sel.type === "league") return m.league === sel.code;
  if (sel.type === "team") return m.home_id === sel.id || m.away_id === sel.id;
  const lg = catalog.find((c) => c.code === m.league);
  if (!lg) return false;
  return sel.type === "country" ? lg.country === sel.value : lg.continent === sel.value;
}
function leagueSelLabel(sel) {
  if (!sel || sel.type === "all") return "Todas las ligas";
  if (sel.type === "league" || sel.type === "team") return sel.name;
  return sel.type === "country" ? `Todas · ${sel.value}` : `Todas · ${sel.value}`;
}

// Equipos de los próximos partidos (para buscar un equipo directamente, sin pasar por su liga).
function teamIndex(matches, catalog) {
  const byId = new Map();
  for (const m of matches) {
    for (const [id, name] of [[m.home_id, m.home], [m.away_id, m.away]]) {
      if (id == null) continue;
      const t = byId.get(id) || { id, name, league: m.league, league_name: m.league_name, n: 0,
        country: (catalog.find((c) => c.code === m.league) || {}).country || "" };
      t.n += 1;
      byId.set(id, t);
    }
  }
  return [...byId.values()];
}
function teamScore(t, q) {
  if (!q) return 0;
  const name = normTxt(t.name);
  let total = 0;
  for (const tok of q.split(/\s+/).filter(Boolean)) {
    let s = 0;
    if (name === tok) s = 130;
    else if (name.startsWith(tok)) s = 105;
    else if (name.split(/[\s.'-]+/).some((w) => w.startsWith(tok))) s = 90;
    else if (name.includes(tok)) s = 70;
    if (!s) return 0;
    total += s;
  }
  return total;
}

async function mountLeaguePicker(root, opts) {
  const catalog = await leagueCatalog();
  const teams = teamIndex(await api("/api/upcoming").catch(() => []), catalog);
  const st = { sel: opts.value || { type: "all" }, q: "", continent: "", country: "", onlyActive: true, open: false, idx: 0, items: [] };
  const total = catalog.reduce((a, c) => a + c.n, 0);
  root.classList.add("lp");
  root.innerHTML = `
    <button type="button" class="lp-trigger" aria-haspopup="listbox">
      <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <span class="lp-current"></span>
      <svg class="ico lp-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>
    </button>
    <button type="button" class="lp-clear" title="Quitar filtro" aria-label="Quitar filtro">×</button>
    <div class="lp-pop" role="dialog" hidden>
      <div class="lp-search">
        <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input type="text" placeholder="Buscar equipo, liga, país o continente…" autocomplete="off" spellcheck="false" aria-label="Buscar equipo o liga">
        <kbd>Esc</kbd>
      </div>
      <div class="lp-filters">
        <div class="lp-conts"></div>
        <div class="lp-row">
          <select class="lp-country" aria-label="País"></select>
          <label class="lp-switch"><input type="checkbox" checked><span></span>Solo con partidos</label>
        </div>
      </div>
      <div class="lp-list" role="listbox"></div>
      <div class="lp-foot"><span class="lp-count"></span><span>↑↓ moverse · Enter elegir</span></div>
    </div>`;
  const $r = (s) => root.querySelector(s);
  const input = $r("input[type=text]"), pop = $r(".lp-pop"), list = $r(".lp-list");

  const renderTrigger = () => {
    const sel = st.sel;
    const n = sel.type === "all" ? total : catalog.filter((c) => leagueSelMatch(sel, { league: c.code }, catalog)).reduce((a, c) => a + c.n, 0);
    const nShown = sel.type === "team" ? (teams.find((t) => t.id === sel.id) || { n: 0 }).n : n;
    const icon = sel.type === "league" ? leagueLogo(sel.code, 18) : sel.type === "team" ? teamLogo(sel.id, sel.name, 18) : "";
    $r(".lp-current").innerHTML = `${icon}<b>${esc(leagueSelLabel(sel))}</b><span class="lp-n">${nShown} ${nShown === 1 ? "partido" : "partidos"}</span>`;
    root.classList.toggle("has-sel", sel.type !== "all");
  };
  const renderFilters = () => {
    $r(".lp-conts").innerHTML = ["", ...CONTINENTS].map((c) =>
      `<button type="button" class="lp-cont ${st.continent === c ? "on" : ""}" data-c="${esc(c)}">${c || "Todos"}</button>`).join("");
    const countries = [...new Set(catalog.filter((c) => !st.continent || c.continent === st.continent).map((c) => c.country))].sort((a, b) => a.localeCompare(b));
    if (st.country && !countries.includes(st.country)) st.country = "";
    $r(".lp-country").innerHTML = `<option value="">Todos los países</option>` +
      countries.map((c) => `<option ${c === st.country ? "selected" : ""}>${esc(c)}</option>`).join("");
  };
  const renderList = () => {
    const q = normTxt(st.q.trim());
    let rows = catalog
      .filter((c) => (!st.continent || c.continent === st.continent) && (!st.country || c.country === st.country) && (!st.onlyActive || c.n > 0))
      .map((c) => ({ c, s: leagueScore(c, q) })).filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s || b.c.n - a.c.n || a.c.name.localeCompare(b.c.name));
    const groups = [];
    if (!q) {
      groups.push({ sel: { type: "all" }, label: "Todas las ligas", sub: `${total} partidos`, n: total });
      if (st.continent) {
        const n = catalog.filter((c) => c.continent === st.continent).reduce((a, c) => a + c.n, 0);
        groups.push({ sel: { type: "continent", value: st.continent }, label: `Todas las de ${st.continent}`, sub: `${n} partidos`, n });
      }
      if (st.country) {
        const n = catalog.filter((c) => c.country === st.country).reduce((a, c) => a + c.n, 0);
        groups.push({ sel: { type: "country", value: st.country }, label: `Todas las de ${st.country}`, sub: `${n} partidos`, n });
      }
    }
    // Equipos: solo al escribir, respetando los filtros de continente y país de su liga.
    const teamRows = !q ? [] : teams
      .filter((t) => { const lg = catalog.find((c) => c.code === t.league) || {};
        return (!st.continent || lg.continent === st.continent) && (!st.country || lg.country === st.country); })
      .map((t) => ({ t, s: teamScore(t, q) })).filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s || a.t.name.localeCompare(b.t.name)).slice(0, 12);
    st.items = [...groups.map((g) => ({ kind: "group", ...g })),
      ...teamRows.map((x, k) => ({ kind: "team", t: x.t, head: k === 0 ? "Equipos" : null })),
      ...rows.map((x, k) => ({ kind: "league", c: x.c, head: k === 0 && teamRows.length ? "Ligas" : null }))];
    st.idx = Math.min(st.idx, Math.max(st.items.length - 1, 0));
    list.innerHTML = st.items.length ? st.items.map((it, i) => (it.head ? `<div class="lp-head">${it.head}</div>` : "") + (it.kind === "team"
      ? `<div class="lp-item ${i === st.idx ? "act" : ""} ${st.sel.type === "team" && st.sel.id === it.t.id ? "cur" : ""}" data-i="${i}" role="option">
           ${teamLogo(it.t.id, it.t.name, 22)}
           <span class="lp-txt"><b>${highlight(it.t.name, q)}</b><small>${esc(it.t.league_name)} · ${esc(it.t.country)}</small></span>
           <span class="lp-cnt">${it.t.n}</span></div>`
      : it.kind === "group"
      ? `<div class="lp-item grp ${i === st.idx ? "act" : ""}" data-i="${i}" role="option">
           <span class="lp-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M6 12h12M10 18h4"/></svg></span>
           <span class="lp-txt"><b>${esc(it.label)}</b><small>${esc(it.sub)}</small></span></div>`
      : `<div class="lp-item ${i === st.idx ? "act" : ""} ${it.c.n ? "" : "dim"} ${st.sel.type === "league" && st.sel.code === it.c.code ? "cur" : ""}" data-i="${i}" role="option">
           ${leagueLogo(it.c.code, 22)}
           <span class="lp-txt"><b>${highlight(it.c.name, q)}</b><small>${highlight(it.c.country, q)} · ${esc(it.c.continent)}</small></span>
           <span class="lp-cnt">${it.c.n || "—"}</span></div>`)).join("")
      : `<div class="lp-none">Sin coincidencias${st.onlyActive ? ". Prueba desactivando «Solo con partidos»." : "."}</div>`;
    $r(".lp-count").textContent = `${teamRows.length ? `${teamRows.length} ${teamRows.length === 1 ? "equipo" : "equipos"} · ` : ""}${rows.length} ${rows.length === 1 ? "liga" : "ligas"}`;
    const act = list.querySelector(".lp-item.act");
    if (act) act.scrollIntoView({ block: "nearest" });
  };
  const choose = (i) => {
    const it = st.items[i];
    if (!it) return;
    st.sel = it.kind === "group" ? it.sel : it.kind === "team" ? { type: "team", id: it.t.id, name: it.t.name }
      : { type: "league", code: it.c.code, name: it.c.name };
    close();
    renderTrigger();
    opts.onChange(st.sel);
  };
  const open = () => {
    if (st.open) return;
    st.open = true; pop.hidden = false; root.classList.add("open");
    // Si a la derecha no cabe, el panel se alinea al borde derecho del buscador (no se sale de la pantalla).
    root.classList.toggle("flip", root.getBoundingClientRect().left + pop.offsetWidth > document.documentElement.clientWidth - 8);
    st.q = ""; input.value = ""; st.idx = 0;
    renderFilters(); renderList();
    setTimeout(() => input.focus(), 0);
  };
  const close = () => { st.open = false; pop.hidden = true; root.classList.remove("open"); };

  $r(".lp-trigger").onclick = () => (st.open ? close() : open());
  $r(".lp-clear").onclick = (e) => { e.stopPropagation(); st.sel = { type: "all" }; renderTrigger(); opts.onChange(st.sel); };
  input.oninput = () => { st.q = input.value; st.idx = 0; renderList(); };
  input.onkeydown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); st.idx = Math.min(st.idx + 1, st.items.length - 1); renderList(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); st.idx = Math.max(st.idx - 1, 0); renderList(); }
    else if (e.key === "Enter") { e.preventDefault(); choose(st.idx); }
    else if (e.key === "Escape") { close(); $r(".lp-trigger").focus(); }
  };
  $r(".lp-conts").onclick = (e) => {
    const b = e.target.closest(".lp-cont"); if (!b) return;
    st.continent = b.dataset.c; st.idx = 0; renderFilters(); renderList(); input.focus();
  };
  $r(".lp-country").onchange = (e) => { st.country = e.target.value; st.idx = 0; renderList(); input.focus(); };
  $r(".lp-switch input").onchange = (e) => { st.onlyActive = e.target.checked; st.idx = 0; renderList(); input.focus(); };
  list.onmousemove = (e) => {
    const it = e.target.closest(".lp-item"); if (!it || +it.dataset.i === st.idx) return;
    list.querySelector(".lp-item.act")?.classList.remove("act"); it.classList.add("act"); st.idx = +it.dataset.i;
  };
  list.onclick = (e) => { const it = e.target.closest(".lp-item"); if (it) choose(+it.dataset.i); };
  document.addEventListener("mousedown", (e) => { if (st.open && !root.contains(e.target)) close(); });
  renderTrigger();
  return { set(sel) { st.sel = sel; renderTrigger(); }, catalog };
}

/* ---------- filtro por día (los próximos partidos cubren hoy, mañana y pasado mañana) ---------- */
// Selección: { type: "all" | "today" | "tomorrow" | "after" } (días en hora local).
const localDay = (d) => { const x = new Date(d); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`; };
const dayOffset = (n) => { const t = new Date(); t.setDate(t.getDate() + n); return localDay(t); };
function dateSelMatch(sel, kickoff) {
  if (!sel || sel.type === "all") return true;
  const n = { today: 0, tomorrow: 1, after: 2 }[sel.type];
  return localDay(kickoff) === dayOffset(n);
}
function mountDateFilter(root, opts) {
  const list = opts.list || [];
  let sel = opts.value || { type: "all" };
  const count = (s) => list.filter((m) => dateSelMatch(s, m.kickoff)).length;
  const after = new Intl.DateTimeFormat("es-CL", { weekday: "long" }).format(new Date(Date.now() + 2 * 864e5));
  const draw = () => {
    const btn = (type, label) => {
      const n = count({ type });
      return `<button type="button" class="df-btn ${sel.type === type ? "on" : ""}" data-t="${type}" ${n || type === "all" ? "" : "disabled"}>${label}<span>${n}</span></button>`;
    };
    root.innerHTML = `<div class="df">${btn("all", "Todos")}${btn("today", "Hoy")}${btn("tomorrow", "Mañana")}${btn("after", after[0].toUpperCase() + after.slice(1))}</div>`;
  };
  root.onclick = (e) => {
    const b = e.target.closest(".df-btn"); if (!b || b.disabled) return;
    sel = { type: b.dataset.t }; draw(); opts.onChange(sel);
  };
  draw();
}
