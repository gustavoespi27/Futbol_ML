"use strict";
/* Combinadas: lista de partidos con sus opciones, boleto (agregar / quitar) e histórico 2026.
   Usa los helpers de app.js ($, api, pct, num, signed, esc, fmtDate, chart, baseOptions, css, stat, probBar). */

const ticket = { legs: [], groupOdds: {} };
try { Object.assign(ticket, JSON.parse(localStorage.getItem("ticket") || "{}")); } catch (e) { /* sin storage */ }
const saveTicket = () => { try { localStorage.setItem("ticket", JSON.stringify(ticket)); } catch (e) { /* */ } };
const hasLeg = (ref, key) => ticket.legs.some((l) => l.ref === ref && l.key === key);
let cbSel = { type: "all" }, cbDate = { type: "all" };
let openRef = null;
let cbRedraw = null;      // redibuja la lista de Combinadas (los partidos del boleto van primero)

let legCount = ticket.legs.length;
function afterTicketChange() {
  if (ticket.legs.length > legCount) {            // se agregó una selección: el contador late
    document.querySelectorAll("[data-ticket-count]").forEach((b) => {
      b.classList.remove("pulse"); void b.offsetWidth; b.classList.add("pulse");
    });
  }
  legCount = ticket.legs.length;
  const refs = new Set(ticket.legs.map((l) => l.ref));
  Object.keys(ticket.groupOdds).forEach((r) => { if (!refs.has(r)) delete ticket.groupOdds[r]; });
  saveTicket(); syncAddButtons(); refreshTicket();
  if (cbRedraw && document.querySelector("#v-combinadas.active")) cbRedraw();
  if (window.__toTopUpdate) window.__toTopUpdate();
}
function toggleLeg(ref, key) {
  if (hasLeg(ref, key)) ticket.legs = ticket.legs.filter((l) => !(l.ref === ref && l.key === key));
  else ticket.legs.push({ ref, key });
  afterTicketChange();
}
function toggleVariant(ref, keys) {
  const all = keys.every((k) => hasLeg(ref, k));
  if (all) ticket.legs = ticket.legs.filter((l) => !(l.ref === ref && keys.includes(l.key)));
  else keys.forEach((k) => { if (!hasLeg(ref, k)) ticket.legs.push({ ref, key: k }); });
  afterTicketChange();
}
function syncAddButtons() {
  document.querySelectorAll("button.add[data-ref]").forEach((b) => {
    const on = b.dataset.keys.split(",").every((k) => hasLeg(b.dataset.ref, k));
    b.classList.toggle("on", on);
    b.textContent = on ? "✓" : "+";
    b.title = on ? "Quitar de la combinada" : "Agregar a la combinada";
  });
  const n = ticket.legs.length;
  document.querySelectorAll("[data-ticket-count]").forEach((el) => { el.textContent = n ? String(n) : ""; });
}
let lastRef = null;
document.addEventListener("click", (e) => {
  const b = e.target.closest("button.add[data-ref]");
  if (!b) return;
  e.preventDefault();
  const keys = b.dataset.keys.split(",");
  lastRef = b.dataset.ref;
  if (keys.length > 1) toggleVariant(b.dataset.ref, keys); else toggleLeg(b.dataset.ref, keys[0]);
});

/* ---------- opciones de un partido ---------- */
function optionsTable(ctx) {
  if (!ctx.options || !ctx.options.length) return `<div class="empty">Sin probabilidades disponibles para este partido.</div>`;
  let group = "";
  const rows = ctx.options.map((o) => {
    const head = o.group !== group ? `<tr class="opt-group"><td colspan="6">${esc(o.group)}</td></tr>` : "";
    group = o.group;
    const odds = o.odds ? `${num(o.odds)}${o.estimated ? '<span title="Estimada desde el 1X2 de la misma casa" style="color:var(--muted)">*</span>' : ""}` : "–";
    const val = vchip(o.verdict, o.odds && o.ev != null ? signed(o.ev) : "");
    return `${head}<tr><td>${esc(o.label)}</td><td class="r"><b>${pct(o.p, 1)}</b></td><td class="r">${odds}</td>
      <td class="r" style="color:var(--text-2)">${num(o.fair)}</td><td class="r">${val}</td>
      <td class="r"><button class="add" data-ref="${esc(ctx.ref)}" data-keys="${o.key}">+</button></td></tr>`;
  }).join("");
  const book = (ctx.options.find((o) => o.book) || {}).book;
  return `<div class="table-wrap"><table class="opt-table"><thead><tr><th>Selección</th><th class="r">Probabilidad</th>
    <th class="r">Cuota ${book ? esc(book) : "casa"}</th><th class="r">Cuota justa</th><th class="r">Semáforo · valor</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}
function suggestionsBlock(ctx) {
  if (!ctx.suggestions || !ctx.suggestions.length) return "";
  return `<div><h3 style="margin-bottom:8px">Variantes más probables del partido</h3><div class="sugg">${ctx.suggestions.map((s) => `
    <div class="row"><span>${esc(s.label)}</span><b class="num">${pct(s.p)}</b><span class="num" style="color:var(--muted)">justa ${num(s.fair)}</span>
    <button class="add" data-ref="${esc(ctx.ref)}" data-keys="${s.keys.join(",")}">+</button></div>`).join("")}</div></div>`;
}

/* ---------- vista ---------- */
async function renderCombos() {
  refreshTicket();
  const histP = api("/api/combos/history");
  const [list, catalog] = await Promise.all([api("/api/upcoming"), leagueCatalog()]);
  const draw = () => {
    const box = $("#cb-matches");
    // los partidos que ya están en el boleto van arriba (aunque el filtro no los incluya), en el orden en que se agregaron
    const inTicket = [...new Set(ticket.legs.map((l) => l.ref))];
    const pinned = inTicket.map((r) => list.find((m) => m.ref === r)).filter(Boolean);
    const rest = list.filter((m) => !inTicket.includes(m.ref) && leagueSelMatch(cbSel, m, catalog) && dateSelMatch(cbDate, m.kickoff));
    const shown = [...pinned, ...rest];
    const wasOpen = new Set([...box.querySelectorAll("details.mx[open]")].map((d) => d.dataset.ref));
    const scroll = box.scrollTop;
    box.innerHTML = shown.length ? shown.map((m) => {
      const n = ticket.legs.filter((l) => l.ref === m.ref).length;
      return `
      <details class="mx ${n ? "in-ticket" : ""}" data-ref="${esc(m.ref)}" ${m.ref === openRef || wasOpen.has(m.ref) ? "open" : ""}>
        <summary>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;color:var(--text-2);font-size:12.5px"><span class="lg">${leagueLogo(m.league, 16)}${esc(m.league_name)}</span>
            <span style="display:flex;align-items:center;gap:8px">${n ? `<span class="in-ticket-tag">En tu combinada · ${n} ${n === 1 ? "selección" : "selecciones"}</span>` : ""}${fmtDate(m.kickoff)}</span></div>
          ${teamsRow(m)}
          ${probBar(m.p_official)}
          <div style="color:var(--muted);font-size:12px">Toca para ver todas las opciones · ${esc(m.source)}</div>
        </summary>
        <div class="body">${suggestionsBlock(m)}${optionsTable(m)}
          <p class="sub" style="margin:0">* Doble oportunidad estimada desde el 1X2 de la misma casa. Valor = probabilidad × cuota − 1.</p></div>
      </details>`;
    }).join("") : "";
    if (!shown.length) emptyMatches(box, isFiltered(cbSel, cbDate), reset);
    syncAddButtons();
    box.scrollTop = scroll;
    const focus = openRef || lastRef;
    if (focus) {
      // mantiene a la vista el partido abierto o el que se acaba de agregar / quitar (puede haber cambiado de lugar)
      const el = box.querySelector(`details.mx[data-ref="${CSS.escape(focus)}"]`);
      if (el) {
        const top = el.offsetTop - box.offsetTop;
        if (openRef || top < box.scrollTop || top > box.scrollTop + box.clientHeight - 80) box.scrollTop = Math.max(0, top - 8);
        if (openRef) el.scrollIntoView({ block: "nearest" });
      }
      openRef = null; lastRef = null;
    }
  };
  cbRedraw = draw;
  mountToTop($("#cb-matches"));
  const mount = () => {
    mountLeaguePicker($("#cb-filter"), { value: cbSel, onChange: (s) => { cbSel = s; draw(); } });
    mountDateFilter($("#cb-date"), { list, value: cbDate, onChange: (s) => { cbDate = s; draw(); } });
  };
  const reset = () => { cbSel = { type: "all" }; cbDate = { type: "all" }; mount(); draw(); };
  mount();
  draw();
  renderComboHistory(await histP, list.length);
}

/* ---------- volver arriba: a los partidos de la combinada ---------- */
function mountToTop(box) {
  let btn = document.querySelector(".to-top");
  if (!btn) {
    btn = document.createElement("button");
    btn.type = "button"; btn.className = "to-top";
    document.body.appendChild(btn);
  }
  const update = () => {
    const onView = !!document.querySelector("#v-combinadas.active");
    const far = box.scrollTop > 300 || window.scrollY > box.getBoundingClientRect().top + window.scrollY + 200;
    const n = new Set(ticket.legs.map((l) => l.ref)).size;
    btn.innerHTML = n ? `↑ Tus partidos <b>${n}</b>` : "↑ Volver arriba";
    btn.classList.toggle("show", onView && far);
  };
  btn.onclick = () => {
    box.scrollTo({ top: 0, behavior: "smooth" });
    const top = $("#cb-filter").getBoundingClientRect().top + window.scrollY - 80;
    if (window.scrollY > top) window.scrollTo({ top, behavior: "smooth" });
  };
  box.onscroll = update;
  if (!window.__toTopBound) {
    window.__toTopBound = true;
    window.addEventListener("scroll", () => document.querySelector(".to-top") && window.__toTopUpdate());
    window.addEventListener("hashchange", () => window.__toTopUpdate());
  }
  window.__toTopUpdate = update;
  update();
}

/* ---------- boleto ---------- */
let ticketSeq = 0;
let shownLegs = new Set();                          // selecciones ya dibujadas: las nuevas entran con animación
let lastPay = null;                                 // últimos montos mostrados, para animar el cambio
const QUICK_STAKES = [1000, 5000, 10000, 50000];

// Cambia un número de `from` a `to` en ~350 ms (los montos se actualizan con movimiento, no de golpe).
function animateNumber(el, from, to, fmt) {
  if (from == null || from === to || matchMedia("(prefers-reduced-motion: reduce)").matches) { el.textContent = fmt(to); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / 350), e = 1 - Math.pow(1 - k, 3);
    el.textContent = fmt(from + (to - from) * e);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
// Selecciones del mismo partido: ¿la correlación ayuda o perjudica frente a tratarlas como independientes?
function correlationNote(g) {
  if (!g.same_match || g.impossible || !g.items || g.items.some((it) => !it.p)) return "";
  const indep = g.items.reduce((acc, it) => acc * it.p, 1);
  const ratio = g.p / indep;
  if (ratio > 1.03) return `<span class="corr up" title="Probabilidad conjunta ${pct(g.p, 1)} vs ${pct(indep, 1)} si fueran independientes">▲ La correlación favorece: ocurren juntas ${signed(ratio - 1, 0)} más que por separado</span>`;
  if (ratio < 0.97) return `<span class="corr down" title="Probabilidad conjunta ${pct(g.p, 1)} vs ${pct(indep, 1)} si fueran independientes">▼ La correlación penaliza: ocurren juntas ${signed(ratio - 1, 0)} respecto de por separado</span>`;
  return `<span class="corr">Casi independientes entre sí</span>`;
}
async function refreshTicket() {
  const el = $("#ticket");
  if (!el) return;
  syncAddButtons();
  if (!ticket.legs.length) {
    el.innerHTML = `<div class="t-head"><h2>Tu boleto</h2><span class="t-type">vacío</span></div>
      <div class="t-empty">Agrega selecciones con <b>+</b>. Puedes combinar varias del mismo partido o de partidos distintos.</div>`;
    shownLegs = new Set();
    return;
  }
  const seq = ++ticketSeq;
  let r;
  try {
    r = await api("/api/combo", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ legs: ticket.legs, group_odds: ticket.groupOdds }) });
  } catch (err) {
    el.innerHTML = `<h2>Tu combinada</h2><div class="callout warn"><div>${esc(err.message)}</div></div>
      <button class="chip" id="t-clear">Vaciar combinada</button>`;
    $("#t-clear").onclick = () => { ticket.legs = []; ticket.groupOdds = {}; afterTicketChange(); };
    return;
  }
  if (seq !== ticketSeq) return;
  const stake = getStake();

  // Un bloque por partido; dentro, cada selección es su propia fila con su probabilidad, su cuota y su botón ×.
  const legsHtml = r.groups.map((g) => {
    const single = !g.same_match;
    const [h, a] = g.match.split(" vs ");
    const items = (g.items || g.keys.map((k) => ({ key: k, label: k }))).map((it) => {
      const own = (ticket.legs.find((l) => l.ref === g.ref && l.key === it.key) || {}).odds;
      const oddsCell = single
        ? `<input type="number" step="0.01" min="1.01" value="${own ?? it.odds ?? ""}" data-ref="${esc(g.ref)}" data-key="${it.key}" class="t-odds" title="Cuota de tu casa">`
        : `<span class="sel-odds">${it.odds ? num(it.odds) : "–"}</span>`;
      const id = `${g.ref}|${it.key}`;
      return `<div class="sel-row ${shownLegs.has(id) ? "" : "enter"}">
        <span class="sel-dot"></span>
        <span class="sel-name">${esc(it.label)}</span>
        <span class="sel-p num">${pct(it.p, 1)}</span>
        ${oddsCell}
        <button class="x" title="Quitar «${esc(it.label)}»" aria-label="Quitar ${esc(it.label)}" data-ref="${esc(g.ref)}" data-key="${it.key}">✕</button>
      </div>`;
    }).join("");
    const joint = g.same_match ? `<div class="sel-joint">
        <span>${g.impossible ? '<span class="pill bad">imposible: se contradicen</span>' : `Juntas en este partido: <b>${pct(g.p, 1)}</b> · justa ${num(g.fair)}`}</span>
        ${correlationNote(g)}
        <label>cuota de tu casa<input type="number" step="0.01" min="1.01" value="${ticket.groupOdds[g.ref] ?? ""}" placeholder="—"
          data-ref="${esc(g.ref)}" data-key="" class="t-odds"></label></div>` : "";
    return `<div class="leg-group ${g.same_match ? "same" : ""}">
      <div class="lg-match"><div class="mt">${matchTag({ home: h, away: a, home_id: g.home_id, away_id: g.away_id }, 16)}</div>
        <small>${leagueLogo(g.league, 12)} ${esc(g.league_name)}${g.kickoff ? ` · ${fmtDate(g.kickoff)}` : ""}</small></div>
      ${items}${joint}
    </div>`;
  }).join("");

  const odds = r.book_odds;
  const hist = r.history;
  let verdict;
  if (r.ev == null) {
    verdict = `<div class="callout"><div>Ingresa la cuota que te ofrece tu casa${r.groups.some((g) => g.same_match) ? " para las variantes del mismo partido" : ""} para calcular si la combinada tiene valor.</div></div>`;
  } else if (r.ev > 0) {
    verdict = `<div class="callout"><div><b>La cuota paga más de lo que vale según el sistema</b> (valor esperado ${signed(r.ev)} por unidad). Aun así, no hay ventaja demostrada: trátalo como un experimento.</div></div>`;
  } else {
    verdict = `<div class="callout warn"><div><b>Valor esperado ${signed(r.ev)} por unidad:</b> la casa paga menos de lo que vale esta combinada según el sistema. A la larga, pierde.</div></div>`;
  }
  const nSel = r.groups.reduce((a, g) => a + g.keys.length, 0);
  const type = nSel === 1 ? "Simple" : r.groups.length === 1 ? "Mismo partido" : "Combinada";
  el.innerHTML = `
    <div class="t-head"><h2>Tu boleto</h2><span class="t-type">${type}<b>${nSel}</b></span>
      <button class="t-clear" id="t-clear" title="Quitar todas las selecciones">Vaciar</button></div>
    <div class="legs">${legsHtml}</div>
    <div><div style="color:var(--text-2);font-size:13px">Probabilidad de acertarla</div>
      <div class="big-p num">${pct(r.p, 1)}</div>
      <div style="color:var(--muted);font-size:12.5px;margin-top:4px">${r.p > 0 ? `≈ 1 de cada ${Math.max(1, Math.round(1 / r.p))} veces` : "imposible: hay selecciones contradictorias"}</div></div>
    <div class="kv">
      <div><span>Cuota ${nSel === 1 ? "" : "combinada"}${odds ? "" : " (justa)"}</span><b class="num">${num(odds || r.fair_odds)}</b></div>
      <div><span>Monto a apostar ($)</span><input id="t-stake" type="number" min="1" step="any" value="${stake}" style="padding:4px 8px"></div>
    </div>
    <div class="t-chips">${QUICK_STAKES.map((v) => `<button type="button" class="t-chip" data-v="${v}">${clp(v)}</button>`).join("")}</div>
    <div id="t-payout"></div>
    ${verdict}
    ${hist ? `<p class="sub" style="margin:0">En 2026, las combinadas de ${hist.legs} ${hist.legs === 1 ? "selección" : "partidos"} con las opciones más probables
      se acertaron el ${pct(hist.hit)} de las veces (el sistema esperaba ${pct(hist.p_mean)}) y rindieron ${signed(hist.yield)} por unidad.</p>` : ""}`;

  $("#t-clear").onclick = () => { ticket.legs = []; ticket.groupOdds = {}; afterTicketChange(); };
  el.querySelectorAll("button.x").forEach((b) => { b.onclick = () => toggleLeg(b.dataset.ref, b.dataset.key); });
  el.querySelectorAll("input.t-odds").forEach((inp) => {
    inp.onchange = () => {
      const v = parseFloat(inp.value);
      if (inp.dataset.key) {
        const leg = ticket.legs.find((l) => l.ref === inp.dataset.ref && l.key === inp.dataset.key);
        if (leg) { if (v > 1) leg.odds = v; else delete leg.odds; }
      } else if (v > 1) ticket.groupOdds[inp.dataset.ref] = v;
      else delete ticket.groupOdds[inp.dataset.ref];
      saveTicket(); refreshTicket();
    };
  });
  const drawPay = () => {
    const st = parseFloat($("#t-stake").value) || 0;
    const o = odds || r.fair_odds;
    el.querySelectorAll(".t-chip").forEach((c) => c.classList.toggle("on", Number(c.dataset.v) === st));
    if (!st || !o) {
      $("#t-payout").innerHTML = `<div class="callout"><div>Ingresa un monto para simular la apuesta.</div></div>`;
      lastPay = null;
      return;
    }
    const pay = payout(st, o, r.p);
    $("#t-payout").innerHTML = `
      <div class="t-win"><span>Ganancia potencial si aciertas</span><b class="num" data-f="net"></b>
        <small>Recibes <b class="num" data-f="ret"></b> en total</small></div>
      <div class="kv payout">
        <div><span>Si fallas, pierdes</span><b class="num" style="color:var(--bad)" data-f="lose"></b></div>
        <div><span>Ganancia esperada</span><b class="num" data-f="expected"
          style="color:${pay.expected >= 0 ? "var(--good)" : "var(--bad)"}"></b></div>
      </div>
      <p class="sub" style="margin:0">Acierta ${pct(r.p, 1)} de las veces según el sistema. La ganancia esperada es el promedio por
        apuesta si la repitieras muchas veces.${odds ? "" : " Calculado con la cuota justa: ingresa la cuota de tu casa en cada selección."}</p>`;
    const fmt = { net: (x) => "+" + clp(x), ret: clp, lose: clp, expected: (x) => (x >= 0 ? "+" : "") + clp(x) };
    $("#t-payout").querySelectorAll("[data-f]").forEach((b) => {
      const f = b.dataset.f;
      animateNumber(b, lastPay ? lastPay[f] : null, pay[f], fmt[f]);
    });
    lastPay = pay;
  };
  $("#t-stake").oninput = (e) => { setStake(e.target.value); drawPay(); };
  el.querySelectorAll(".t-chip").forEach((c) => {
    c.onclick = () => { $("#t-stake").value = c.dataset.v; setStake(c.dataset.v); drawPay(); };
  });
  shownLegs = new Set(r.groups.flatMap((g) => g.keys.map((k) => `${g.ref}|${k}`)));
  drawPay();
}

/* ---------- histórico ---------- */
function renderComboHistory(h, nUpcoming) {
  const pr = h.strategies.probables, va = h.strategies.valor;
  const two = pr.find((r) => r.legs === 2), three = pr.find((r) => r.legs === 3);
  $("#cb-hist-intro").textContent = `Combinadas simuladas con ${h.n_matches.toLocaleString("es-CL")} partidos de 2026 (${fmtDate(h.from, false)} – ${fmtDate(h.to, false)}) ` +
    `que el modelo no vio al entrenar. Se apuesta 1 unidad a cuota de cierre de Bet365 en 1X2 y Más/Menos de 2,5 goles; un partido por pierna.`;
  const cal = h.calibration.find((c) => c.pred > 0.2 && c.pred < 0.3) || h.calibration[0];
  $("#cb-tiles").innerHTML = [
    stat("¿Se cumple el porcentaje?", cal ? `${pct(cal.pred)} → ${pct(cal.obs)}` : "–",
      cal ? `combinadas con ~${pct(cal.pred)} de probabilidad se acertaron el ${pct(cal.obs)}` : ""),
    stat("Dobles más probables", two ? pct(two.hit) : "–", two ? `acertadas en 2026 · rendimiento ${signed(two.yield)}` : ""),
    stat("Triples más probables", three ? pct(three.hit) : "–", three ? `acertadas en 2026 · rendimiento ${signed(three.yield)}` : ""),
    stat("Partidos para combinar", nUpcoming, "próximos 3 días"),
  ].join("");

  const calibSet = (label, pts, color) => ({ label, data: pts.map((c) => ({ x: c.pred * 100, y: c.obs * 100, n: c.n })), ...calibStyle(color) });
  chart("ch-combo-calib", () => ({
    type: "scatter",
    data: { datasets: [
      diagonal(),
      calibSet("Combinadas de 2 a 4 partidos", h.calibration, css("--official")),
      calibSet("Variantes de un mismo partido", h.same_game_calibration, css("--model")),
    ] },
    options: baseOptions({
      interaction: { mode: "nearest", intersect: false },
      plugins: { ...baseOptions().plugins, tooltip: { ...baseOptions().plugins.tooltip, filter: (i) => i.datasetIndex > 0,
        callbacks: { label: (c) => `${c.dataset.label}: dijo ${c.parsed.x.toFixed(0)}%, se acertó ${c.parsed.y.toFixed(0)}% (${c.raw.n.toLocaleString("es-CL")})` } } },
      scales: {
        x: { ...baseOptions().scales.x, type: "linear", min: 0, max: 100, title: { display: true, text: "Probabilidad que dio el sistema", color: css("--muted") }, ticks: { ...baseOptions().scales.x.ticks, callback: (v) => v + "%" } },
        y: { ...baseOptions().scales.y, min: 0, max: 100, title: { display: true, text: "Acertadas de verdad", color: css("--muted") }, ticks: { ...baseOptions().scales.y.ticks, callback: (v) => v + "%" } },
      },
    }),
  }));

  chart("ch-combo-yield", () => ({
    type: "bar",
    data: { labels: pr.map((r) => (r.legs === 1 ? "Simple" : `${r.legs} partidos`)), datasets: [
      { label: "Las más probables", data: pr.map((r) => r.yield * 100), backgroundColor: css("--official"), borderRadius: 6, maxBarThickness: 24, borderSkipped: "start" },
      { label: "Con valor (EV > 0, cuota ≤ 4)", data: va.map((r) => r.yield * 100), backgroundColor: css("--market"), borderRadius: 6, maxBarThickness: 24, borderSkipped: "start" },
    ] },
    options: baseOptions({
      plugins: { ...baseOptions().plugins, tooltip: { ...baseOptions().plugins.tooltip, callbacks: {
        label: (c) => {
          const r = (c.datasetIndex ? va : pr)[c.dataIndex];
          return `${c.dataset.label}: ${c.parsed.y.toFixed(1)}% · ${r.n.toLocaleString("es-CL")} combinadas${r.ci ? ` · IC95% ${signed(r.ci[0], 0)} a ${signed(r.ci[1], 0)}` : ""}`;
        } } } },
      scales: { ...baseOptions().scales, y: { ...baseOptions().scales.y, ticks: { ...baseOptions().scales.y.ticks, callback: (v) => v + "%" } } },
    }),
  }));

  const verdict = (r) => {
    if (r.ci && r.ci[0] > 0) return '<span class="pill good">ganancia significativa</span>';
    if (r.ci && r.ci[1] < 0) return '<span class="pill bad">pérdida segura</span>';
    return '<span class="pill">no concluyente</span>';
  };
  const row = (name, r) => `<tr><td>${name}</td><td class="r">${r.legs}</td><td class="r">${r.n.toLocaleString("es-CL")}</td><td class="r">${pct(r.p_mean, 1)}</td>
    <td class="r"><b>${pct(r.hit, 1)}</b></td><td class="r">${num(r.odds_mean)}</td>
    <td class="r">${r.yield > 0 ? `<span class="pill good">${signed(r.yield)}</span>` : `<span class="pill bad">${signed(r.yield)}</span>`}</td>
    <td class="r" style="color:var(--muted)">${r.ci ? `${signed(r.ci[0], 0)} a ${signed(r.ci[1], 0)}` : ""}</td><td>${verdict(r)}</td></tr>`;
  $("#cb-strategies").innerHTML = `<table><thead><tr><th>Estrategia</th><th class="r">Partidos</th><th class="r">Combinadas</th><th class="r">Prob. esperada</th>
    <th class="r">Acierto real</th><th class="r">Cuota mediana</th><th class="r">Rendimiento</th><th class="r">IC 95%</th><th></th></tr></thead>
    <tbody>${pr.map((r) => row("Las más probables", r)).join("")}${va.map((r) => row("Con valor", r)).join("")}</tbody></table>`;
  const v3 = va.find((r) => r.legs === 3);
  $("#cb-reading").innerHTML = `
    <p><b style="color:var(--text)">Los porcentajes se cumplen:</b> en el gráfico de calibración los puntos van sobre la diagonal, así que la probabilidad que ves al armar una combinada es una estimación honesta.</p>
    <p><b style="color:var(--text)">Combinar las opciones más probables pierde más cuanto más largo el boleto</b>, porque cada pierna arrastra el margen de la casa (${pr.map((r) => signed(r.yield, 0)).join(" → ")}).</p>
    <p><b style="color:var(--text)">Las combinadas "con valor" salen positivas en 2026${v3 ? ` (triples ${signed(v3.yield, 0)})` : ""}, pero son pocas y el intervalo de confianza incluye pérdidas grandes:</b>
      todavía no es una ventaja demostrada. Para comprobarlo hay que seguirlas en papel varios meses antes de arriesgar dinero.</p>`;

  const sel = $("#cb-pattern-league");
  const drawPatterns = () => {
    const rows = (sel.value === "all" ? h.patterns.all : h.patterns.by_league[sel.value]).slice(0, 12);
    $("#cb-patterns").innerHTML = `<table><thead><tr><th>Combinación</th><th class="r">Se cumplió</th><th class="r">El sistema esperaba</th><th class="r">Cuota justa</th><th class="r">Partidos</th></tr></thead>
      <tbody>${rows.map((r) => `<tr><td>${esc(r.label)}</td><td class="r"><b>${pct(r.freq, 1)}</b></td><td class="r">${pct(r.pred, 1)}</td>
        <td class="r" style="color:var(--text-2)">${num(1 / r.freq)}</td><td class="r" style="color:var(--muted)">${r.n.toLocaleString("es-CL")}</td></tr>`).join("")}</tbody></table>`;
  };
  api("/api/leagues").catch(() => []).then((ls) => {
    const names = Object.fromEntries((ls || []).map((l) => [l.code, l.name]));
    sel.innerHTML = `<option value="all">Todas las ligas</option>` + Object.keys(h.patterns.by_league)
      .sort((a, b) => (names[a] || a).localeCompare(names[b] || b))
      .map((c) => `<option value="${c}">${esc(names[c] || c)}</option>`).join("");
    sel.onchange = drawPatterns;
    drawPatterns();
  });
}

function goToCombos(ref) {
  openRef = ref;
  cbSel = { type: "all" };
  if (location.hash === "#combinadas") renderCombos(); else location.hash = "#combinadas";
}
