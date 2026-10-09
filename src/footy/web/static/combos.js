"use strict";
/* Combinadas: lista de partidos con sus opciones, boleto (agregar / quitar) e histórico 2026.
   Usa los helpers de app.js ($, api, pct, num, signed, esc, fmtDate, chart, baseOptions, css, stat, probBar). */

const ticket = { legs: [], groupOdds: {} };
try { Object.assign(ticket, JSON.parse(localStorage.getItem("ticket") || "{}")); } catch (e) { /* sin storage */ }
const saveTicket = () => { try { localStorage.setItem("ticket", JSON.stringify(ticket)); } catch (e) { /* */ } };
const hasLeg = (ref, key) => ticket.legs.some((l) => l.ref === ref && l.key === key);
let cbSel = { type: "all" };
let openRef = null;

function afterTicketChange() {
  const refs = new Set(ticket.legs.map((l) => l.ref));
  Object.keys(ticket.groupOdds).forEach((r) => { if (!refs.has(r)) delete ticket.groupOdds[r]; });
  saveTicket(); syncAddButtons(); refreshTicket();
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
document.addEventListener("click", (e) => {
  const b = e.target.closest("button.add[data-ref]");
  if (!b) return;
  e.preventDefault();
  const keys = b.dataset.keys.split(",");
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
    const shown = list.filter((m) => leagueSelMatch(cbSel, m, catalog));
    $("#cb-matches").innerHTML = shown.length ? shown.map((m) => `
      <details class="mx" data-ref="${esc(m.ref)}" ${m.ref === openRef ? "open" : ""}>
        <summary>
          <div style="display:flex;justify-content:space-between;color:var(--text-2);font-size:12.5px"><span class="lg">${leagueLogo(m.league, 16)}${esc(m.league_name)}</span><span>${fmtDate(m.kickoff)}</span></div>
          ${teamsRow(m)}
          ${probBar(m.p_official)}
          <div style="color:var(--muted);font-size:12px">Toca para ver todas las opciones · ${esc(m.source)}</div>
        </summary>
        <div class="body">${suggestionsBlock(m)}${optionsTable(m)}
          <p class="sub" style="margin:0">* Doble oportunidad estimada desde el 1X2 de la misma casa. Valor = probabilidad × cuota − 1.</p></div>
      </details>`).join("") : `<div class="card empty">No hay partidos programados en los próximos 7 días.</div>`;
    syncAddButtons();
    if (openRef) {
      const el = document.querySelector(`details.mx[data-ref="${CSS.escape(openRef)}"]`);
      if (el) el.scrollIntoView({ block: "start" });
      openRef = null;
    }
  };
  mountLeaguePicker($("#cb-filter"), { value: cbSel, onChange: (s) => { cbSel = s; draw(); } });
  draw();
  renderComboHistory(await histP, list.length);
}

/* ---------- boleto ---------- */
let ticketSeq = 0;
async function refreshTicket() {
  const el = $("#ticket");
  if (!el) return;
  syncAddButtons();
  if (!ticket.legs.length) {
    el.innerHTML = `<h2>Tu combinada</h2><div class="empty" style="padding:12px 0">Agrega selecciones con <b>+</b>.
      Puedes combinar varias del mismo partido o de partidos distintos.</div>`;
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

  const legsHtml = r.groups.map((g) => {
    const single = !g.same_match;
    const own = single ? (ticket.legs.find((l) => l.ref === g.ref && l.key === g.keys[0]) || {}).odds : ticket.groupOdds[g.ref];
    const value = own ?? (single ? g.odds : "");
    const removes = g.keys.map((k) => `<button class="x" title="Quitar ${esc(k)}" data-ref="${esc(g.ref)}" data-key="${k}">×</button>`).join("");
    return `<div class="leg">
      <div><b>${esc(g.label)}</b><div class="m">${(() => { const [h, a] = g.match.split(" vs "); return matchTag({ home: h, away: a, home_id: g.home_id, away_id: g.away_id }, 16); })()}
        <div>${leagueLogo(g.league, 12)} ${esc(g.league_name)}</div></div></div>
      <div style="text-align:right"><b class="num">${pct(g.p, 1)}</b></div>
      <div class="tags">
        ${g.impossible ? '<span class="pill bad">imposible</span>' : ""}
        ${g.same_match ? '<span class="pill warn" title="Probabilidad conjunta calculada desde la matriz de marcadores">mismo partido</span>' : ""}
        <span style="color:var(--muted);font-size:12px">justa ${num(g.fair)}</span>
        <label style="display:flex;flex-direction:row;align-items:center;gap:6px;font-size:12px">cuota
          <input type="number" step="0.01" min="1.01" value="${value ?? ""}" placeholder="${single ? "" : "tu casa"}"
            data-ref="${esc(g.ref)}" data-key="${single ? g.keys[0] : ""}" class="t-odds"></label>
        <span style="margin-left:auto">${removes}</span>
      </div></div>`;
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
  el.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center"><h2>Tu combinada</h2>
      <button class="chip" id="t-clear">Vaciar</button></div>
    <div>${legsHtml}</div>
    <div><div style="color:var(--text-2);font-size:13px">Probabilidad de acertarla</div>
      <div class="big-p num">${pct(r.p, 1)}</div>
      <div style="color:var(--muted);font-size:12.5px;margin-top:4px">${r.p > 0 ? `≈ 1 de cada ${Math.max(1, Math.round(1 / r.p))} veces` : "imposible: hay selecciones contradictorias"}</div></div>
    <div class="kv">
      <div><span>Cuota combinada${odds ? "" : " (justa)"}</span><b class="num">${num(odds || r.fair_odds)}</b></div>
      <div><span>Monto a apostar ($)</span><input id="t-stake" type="number" min="1" step="any" value="${stake}" style="padding:4px 8px"></div>
    </div>
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
    $("#t-payout").innerHTML = payoutBox(st, odds || r.fair_odds, r.p,
      odds ? "" : "Calculado con la cuota justa del sistema: ingresa la cuota de tu casa en cada selección para el retorno real.");
  };
  $("#t-stake").oninput = (e) => { setStake(e.target.value); drawPay(); };
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
    stat("Partidos para combinar", nUpcoming, "próximos 7 días"),
  ].join("");

  const calibSet = (label, pts, color) => ({ label, data: pts.map((c) => ({ x: c.pred * 100, y: c.obs * 100, n: c.n })), showLine: true,
    borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 4.5, pointBorderColor: css("--surface"), pointBorderWidth: 2 });
  chart("ch-combo-calib", () => ({
    type: "scatter",
    data: { datasets: [
      { label: "Calibración perfecta", data: [{ x: 0, y: 0 }, { x: 100, y: 100 }], showLine: true, borderColor: css("--muted"), borderWidth: 1, pointRadius: 0 },
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
      { label: "Las más probables", data: pr.map((r) => r.yield * 100), backgroundColor: css("--official"), borderRadius: 4, maxBarThickness: 24, borderSkipped: "start" },
      { label: "Con valor (EV > 0, cuota ≤ 4)", data: va.map((r) => r.yield * 100), backgroundColor: css("--market"), borderRadius: 4, maxBarThickness: 24, borderSkipped: "start" },
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
