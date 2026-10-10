"use strict";
/* Apuestas sugeridas: regla de valor con riesgo acotado, montos por Kelly fraccionado, histórico 2026 y registro real.
   Usa los helpers de app.js y los botones "+" de combos.js. */

const RISK_PILL = { bajo: "good", medio: "warn", alto: "bad" };
const money = (x) => (x == null ? "–" : "$" + Math.round(x).toLocaleString("es-CL"));

function getBank() {
  try { return Number(localStorage.getItem("bankroll")) || 100000; } catch (e) { return 100000; }
}

async function renderSuggestions() {
  const d = await api("/api/suggestions");
  const inp = $("#sg-bank");
  inp.value = getBank();
  inp.onchange = () => {
    try { localStorage.setItem("bankroll", inp.value); } catch (e) { /* sin storage */ }
    drawCurrent(d);
  };
  drawCurrent(d);
  drawLedger(d.ledger || {});
  drawProBacktest(d.pro_backtest || {}, d.ledger || {});
  return d;
}

async function renderRuleHistory() {
  const d = await api("/api/suggestions");
  drawHistory(d.history || {});
}

function drawCurrent(d) {
  const bank = getBank();
  const r = d.rules;
  setTabCount("value", d.singles.length);
  setTabCount("near", d.closest.length);
  $("#sg-singles").innerHTML = d.singles.length ? d.singles.map((s) => `
    <article class="card sg-card green">
      <div class="meta" style="display:flex;justify-content:space-between;color:var(--text-2);font-size:12.5px">
        <span class="lg">${leagueLogo(s.league, 16)}${esc(s.league_name)}</span><span>${fmtDate(s.kickoff)}</span></div>
      <div><div style="color:var(--text-2);font-size:13.5px">${matchTag(s, 22)}</div>
        <div class="sel">${esc(s.label)}</div></div>
      <div class="reco">${evBadge({ ev: s.ev, verdict: { level: "green", reason: s.reason || "Cumple la regla de valor" } })}
        <span class="pill ${RISK_PILL[s.risk]}">riesgo ${s.risk}</span>
        <span>cuota <b style="color:var(--text)">${num(s.odds)}</b> en ${esc(s.book)}${s.pinnacle ? ` · Pinnacle ${num(s.pinnacle)}` : ""}</span></div>
      <div class="kv">
        <div><span>Probabilidad</span><b class="num">${pct(s.p, 1)}</b></div>
        <div><span>Valor esperado</span><b class="num" style="color:var(--good)">${signed(s.ev)}</b></div>
        <div><span>Precio justo</span><b class="num">${num(1 / s.p)}</b></div>
        <div><span>Monto sugerido</span><b class="num">${money(s.stake * bank)}</b></div>
        <div><span>Si acierta, ganas</span><b class="num">${money(s.stake * bank * (s.odds - 1))}</b></div>
        <div><span>% del bankroll</span><b class="num">${pct(s.stake, 1)}</b></div>
      </div>
      ${s.reason ? `<p class="why"><b>Por qué:</b> ${esc(s.reason)}</p>` : ""}
      <div class="callout" style="padding:10px 12px;font-size:13px"><div>Antes de apostar revisa la cuota en ${esc(s.book)}: tómala solo si
        sigue en <b>${num((1 + r.min_edge / 2) / s.p)}</b> o más. Si bajó, la ventaja desapareció.</div></div>
      <button class="chip" style="justify-self:start" onclick="toggleLeg('${esc(s.ref)}','${s.key}'); this.textContent='En tu combinada ✓'">Agregar a combinada</button>
    </article>`).join("")
    : `<div class="card empty" style="grid-column:1/-1">Hoy ninguna casa paga ≥ ${signed(r.min_edge, 0)} sobre el precio justo de Pinnacle
       (cuota ≤ ${num(r.max_odds, 1)}) en los ${d.n_matches_sharp} partidos con Pinnacle disponible. Un profesional no fuerza apuestas:
       la mayoría de los días no hay valor. Mira la pestaña «Casi con valor».</div>`;

  $("#sg-doubles-wrap").innerHTML = d.doubles.length ? `<h2 style="margin-bottom:12px">Dobles sugeridas</h2>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>Selecciones</th><th class="r">Probabilidad</th><th class="r">Cuota</th>
      <th class="r">Valor</th><th class="r">Monto</th><th class="r">Si acierta</th><th>Riesgo</th></tr></thead><tbody>${d.doubles.map((x) => `<tr>
      <td>${x.legs.map((l) => `${esc(l.label)} <span style="color:var(--muted)">(${esc(l.home)} vs ${esc(l.away)}, ${num(l.odds)})</span>`).join("<br>")}</td>
      <td class="r"><b>${pct(x.p, 1)}</b></td><td class="r">${num(x.odds)}</td><td class="r">${signed(x.ev)}</td>
      <td class="r">${money(x.stake * bank)}</td><td class="r">${money(x.stake * bank * (x.odds - 1))}</td>
      <td><span class="pill ${RISK_PILL[x.risk]}">${x.risk}</span></td></tr>`).join("")}</tbody></table></div>
      <p class="sub" style="margin:10px 0 0">Una doble multiplica probabilidad y cuota: el valor sube, pero también la probabilidad de perder.</p></div>` : "";

  const minOdds = (c) => c.min_odds ?? (1 + r.min_edge) / c.p;
  $("#sg-closest").innerHTML = d.closest.length ? `<table><thead><tr><th>Partido</th><th>Selección</th><th class="r">Prob.</th>
    <th class="r">Cuota</th><th class="r">Valor</th><th class="r">Cuota mínima</th><th></th></tr></thead><tbody>${d.closest.map((c) => `<tr>
    <td><div class="mt">${matchTag(c, 18)}</div><div style="color:var(--muted);font-size:12px">${leagueLogo(c.league, 12)} ${fmtDate(c.kickoff)}</div></td>
    <td>${esc(c.label)}</td><td class="r">${pct(c.p)}</td><td class="r">${num(c.odds)}</td>
    <td class="r">${vchip(c.verdict, signed(c.ev))}</td><td class="r"><b>${num(minOdds(c))}</b></td>
    <td class="r"><button class="add" data-ref="${esc(c.ref)}" data-keys="${c.key}">+</button></td></tr>`).join("")}</tbody></table>`
    : `<div class="empty">Sin partidos con cuotas en los próximos días.</div>`;

  syncAddButtons();
}

function drawHistory(h) {
  if (!h.n) {
    $("#sg-tiles").innerHTML = `<div class="card empty" style="grid-column:1/-1">Sin histórico disponible.</div>`;
    return;
  }
  $("#sg-tiles").innerHTML = [
    stat("Apuestas sugeridas en 2026", h.n.toLocaleString("es-CL"), `cuota media ${num(h.odds_mean)}`),
    stat("Acierto real", pct(h.hit, 1), `el sistema esperaba ${pct(h.p_mean, 1)}`),
    stat("Rendimiento por unidad", signed(h.yield), h.ci ? `IC95% ${signed(h.ci[0], 0)} a ${signed(h.ci[1], 0)}` : ""),
    stat("Bankroll final (inicio 100)", num(h.kelly_final, 1), `peor caída ${pct(h.kelly_max_dd)}`),
  ].join("");

  chart("ch-sg-bank", () => ({
    type: "scatter",
    data: { datasets: [
      { label: "Punto de partida", data: [{ x: 0, y: 100 }, { x: h.curve.length - 1, y: 100 }], showLine: true, borderColor: css("--muted"), borderWidth: 1, pointRadius: 0 },
      { label: "Bankroll", data: h.curve.map((c, i) => ({ x: i, y: c.b, d: c.d })), showLine: true, borderColor: css("--official"),
        backgroundColor: css("--official"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 5 },
    ] },
    options: baseOptions({
      interaction: { mode: "nearest", intersect: false, axis: "x" },
      plugins: { ...baseOptions().plugins, legend: { display: false }, tooltip: { ...baseOptions().plugins.tooltip, filter: (i) => i.datasetIndex === 1,
        callbacks: { title: (i) => i[0].raw.d, label: (c) => `Bankroll: ${c.parsed.y.toFixed(1)}` } } },
      scales: { x: { ...baseOptions().scales.x, type: "linear", ticks: { display: false }, title: { display: true, text: "Apuestas en orden cronológico (2026)", color: css("--muted") } },
        y: { ...baseOptions().scales.y } },
    }),
  }));

  $("#sg-risk").innerHTML = `<table><thead><tr><th>Riesgo</th><th class="r">Apuestas</th><th class="r">Acierto</th><th class="r">Esperado</th>
    <th class="r">Rendimiento</th><th class="r">IC 95%</th></tr></thead><tbody>${h.by_risk.map((r) => `<tr>
    <td><span class="pill ${RISK_PILL[r.risk]}">${r.risk}</span></td><td class="r">${r.n}</td><td class="r">${pct(r.hit, 1)}</td>
    <td class="r" style="color:var(--muted)">${pct(r.p_mean, 1)}</td><td class="r"><b>${signed(r.yield)}</b></td>
    <td class="r" style="color:var(--muted)">${r.ci ? `${signed(r.ci[0], 0)} a ${signed(r.ci[1], 0)}` : ""}</td></tr>`).join("")}
    ${h.doubles && h.doubles.n ? `<tr><td>Dobles</td><td class="r">${h.doubles.n}</td><td class="r">${pct(h.doubles.hit, 1)}</td><td></td>
      <td class="r"><b>${signed(h.doubles.yield)}</b></td><td class="r" style="color:var(--muted)">${h.doubles.ci ? `${signed(h.doubles.ci[0], 0)} a ${signed(h.doubles.ci[1], 0)}` : ""}</td></tr>` : ""}
    </tbody></table>`;

  $("#sg-reading").innerHTML = `
    <p><b style="color:var(--text)">En 2026 la regla no ganó:</b> ${signed(h.yield)} por unidad en ${h.n} apuestas, y el bankroll
      pasó de 100 a ${num(h.kelly_final, 1)}. El intervalo de confianza es amplio: no demuestra ni pérdida ni ganancia.</p>
    <p><b style="color:var(--text)">Las apuestas "con valor" se aciertan menos de lo que el sistema espera</b> (${pct(h.hit, 1)} vs ${pct(h.p_mean, 1)}):
      cuando una casa paga más que el resto, muchas veces tiene una razón que el modelo no ve.</p>
    <p>Por eso los montos son pequeños (¼ de Kelly, máximo 2,5%): limitan la pérdida mientras se mide la regla con partidos futuros.</p>`;
}

/* ---------- apostador profesional: cartera e histórico ---------- */
function drawLedger(L) {
  setTabCount("bets", (L.items || []).length);
  const st = { ganada: "good", perdida: "bad", abierta: "", anulada: "warn" };
  const SELN = { H: "Local", D: "Empate", A: "Visita" };
  $("#sg-record").innerHTML = L.items && L.items.length ? `<table><thead><tr><th>Partido</th><th>Apuesta</th><th class="r">Cuota</th>
    <th class="r">Ventaja</th><th class="r">Monto</th><th class="r">CLV</th><th>Estado</th></tr></thead><tbody>${L.items.map((it) => `<tr>
    <td><div class="mt">${matchTag(it, 18)}${it.score ? ` <b>${esc(it.score)}</b>` : ""}</div><div style="color:var(--muted);font-size:12px">${leagueLogo(it.league, 12)} ${fmtDate(it.kickoff)}</div></td>
    <td>${SELN[it.sel]} <span style="color:var(--muted)">(${esc(it.book)})</span></td><td class="r">${num(it.odds)}</td>
    <td class="r">${signed(it.edge)}</td><td class="r">${pct(it.stake, 1)}</td>
    <td class="r">${it.clv == null ? "–" : `<span style="color:${it.clv > 0 ? "var(--good)" : "var(--bad)"}">${signed(it.clv)}</span>`}</td>
    <td><span class="pill ${st[it.status]}">${it.status}${it.profit != null ? ` ${it.profit > 0 ? "+" : ""}${num(it.profit, 2)}` : ""}</span></td></tr>
    ${it.reason ? `<tr class="why-row"><td colspan="7">${esc(it.reason)}</td></tr>` : ""}`).join("")}</tbody></table>`
    : `<div class="empty">La cartera está vacía: la tarea diaria registra aquí cada apuesta antes del partido, cuando alguna casa supera el precio justo de Pinnacle.</div>`;
}

function drawProBacktest(bt) {
  if (!bt.test) { $("#pro-bt-table").innerHTML = `<div class="empty">Ejecuta python scripts/pro_backtest.py</div>`; return; }
  $("#pro-bt-sub").textContent = `Misma regla sobre las cuotas tempranas de ${bt.matches.toLocaleString("es-CL")} partidos de 22 ligas europeas; bankroll inicial 100, ¼ de Kelly.`;
  const row = (name, s) => `<tr><td>${name}</td><td class="r">${s.n}</td><td class="r"><b style="color:var(--good)">${signed(s.clv)}</b></td>
    <td class="r">${pct(s.clv_pos)}</td><td class="r">${signed(s.yield)}</td><td class="r" style="color:var(--muted)">${signed(s.ci[0], 0)} a ${signed(s.ci[1], 0)}</td>
    <td class="r">${num(s.kelly_bank, 0)}</td></tr>`;
  $("#pro-bt-table").innerHTML = `<table><thead><tr><th>Período</th><th class="r">Apuestas</th><th class="r">CLV</th><th class="r">Le gana al cierre</th>
    <th class="r">Rendimiento</th><th class="r">IC 95%</th><th class="r">Bankroll</th></tr></thead><tbody>
    ${row(`Selección ${bt.selection.period}`, bt.selection)}${row(`Prueba ${bt.test.period}`, bt.test)}</tbody></table>`;
  $("#pro-bt-reading").innerHTML = `
    <p><b style="color:var(--text)">La señal es el CLV:</b> en la prueba, ${pct(bt.test.clv_pos)} de las apuestas consiguió mejor precio que el cierre
      (CLV medio ${signed(bt.test.clv)}). Las casas blandas corrigen hacia Pinnacle: apostar antes de esa corrección es la ventaja.</p>
    <p><b style="color:var(--text)">La ganancia en dinero es ruidosa</b> (${signed(bt.test.yield)}, IC ${signed(bt.test.ci[0], 0)} a ${signed(bt.test.ci[1], 0)}):
      con cuotas medias ~${num(bt.test.odds_mean, 1)} hacen falta cientos de apuestas más para confirmarla. Peor caída histórica del bankroll: ${pct(bt.max_drawdown)}.</p>
    <p><b style="color:var(--text)">Riesgos reales:</b> las casas limitan las cuentas que ganan, las cuotas tempranas aceptan montos bajos y la cuota puede moverse antes de apostar.</p>`;
  chart("ch-pro-bank", () => ({
    type: "scatter",
    data: { datasets: [
      { label: "Inicio", data: [{ x: 0, y: 100 }, { x: bt.curve.length - 1, y: 100 }], showLine: true, borderColor: css("--muted"), borderWidth: 1, pointRadius: 0 },
      { label: "Bankroll", data: bt.curve.map((c, i) => ({ x: i, y: c.b, d: c.d })), showLine: true, borderColor: css("--good"),
        backgroundColor: css("--good"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 5 },
    ] },
    options: baseOptions({
      interaction: { mode: "nearest", intersect: false, axis: "x" },
      plugins: { ...baseOptions().plugins, legend: { display: false }, tooltip: { ...baseOptions().plugins.tooltip, filter: (i) => i.datasetIndex === 1,
        callbacks: { title: (i) => i[0].raw.d, label: (c) => `Bankroll: ${c.parsed.y.toFixed(1)}` } } },
      scales: { x: { ...baseOptions().scales.x, type: "linear", ticks: { display: false },
        title: { display: true, text: `Apuestas en orden cronológico (${bt.curve[0].d.slice(0, 4)}–${bt.curve[bt.curve.length - 1].d.slice(0, 4)})`, color: css("--muted") } },
        y: { ...baseOptions().scales.y } },
    }),
  }));
}

/* ---------- pestañas y pronósticos fiables ---------- */
function setTabCount(tab, n) {
  const el = document.getElementById(`tab-n-${tab}`);
  if (el) el.textContent = n ? String(n) : "";
}
document.addEventListener("click", (e) => {
  const t = e.target.closest(".tabs .tab");
  if (!t) return;
  const card = t.closest(".card");
  card.querySelectorAll(".tabs .tab").forEach((x) => x.classList.toggle("on", x === t));
  card.querySelectorAll(".tab-pane").forEach((p) => p.classList.toggle("on", p.dataset.pane === t.dataset.tab));
});

async function renderReliable() {
  const d = await api("/api/reliable");
  const R = d.record || {};
  $("#rel-min").textContent = pct(d.min_p);
  setTabCount("reliable", d.today.length);
  setTabCount("picks", (R.items || []).length);
  $("#rel-today").innerHTML = d.today.length ? `<table><thead><tr><th>Partido</th><th>Pronóstico</th><th class="r">Prob.</th>
    <th class="r">Cuota</th><th>Por qué</th><th></th></tr></thead><tbody>${d.today.map((c) => `<tr>
    <td><div class="mt">${matchTag(c, 18)}</div><div style="color:var(--muted);font-size:12px">${leagueLogo(c.league, 12)} ${fmtDate(c.kickoff)}</div></td>
    <td><b>${esc(c.label)}</b><div style="color:var(--muted);font-size:11.5px">${esc(c.market)}</div></td>
    <td class="r"><span class="pbar" style="--w:${(c.p * 100).toFixed(0)}%"><b>${pct(c.p)}</b></span></td>
    <td class="r">${c.odds ? num(c.odds) : "–"}</td>
    <td class="why-cell">${esc(c.reason)}</td>
    <td class="r"><button class="add" data-ref="${esc(c.ref)}" data-keys="${c.key}">+</button></td></tr>`).join("")}</tbody></table>`
    : `<div class="empty">Ningún partido próximo con una opción de ${pct(d.min_p)} o más.</div>`;

  const st = { acierto: "good", fallo: "bad", pendiente: "" };
  $("#rel-record").innerHTML = R.items && R.items.length ? `<table><thead><tr><th>Partido</th><th>Pronóstico</th><th class="r">Prob.</th>
    <th class="r">Resultado</th><th>Estado</th></tr></thead><tbody>${R.items.map((it) => `<tr>
    <td><div class="mt">${matchTag(it, 18)}</div><div style="color:var(--muted);font-size:12px">${leagueLogo(it.league, 12)} ${fmtDate(it.kickoff)}</div></td>
    <td><b>${esc(it.label)}</b></td><td class="r">${pct(it.p)}</td><td class="r"><b>${it.score ? esc(it.score) : "–"}</b></td>
    <td><span class="pill ${st[it.status]}">${it.status}</span></td></tr>
    <tr class="why-row"><td colspan="5">${esc(it.reason || "")}</td></tr>`).join("")}</tbody></table>`
    : `<div class="empty">Aún no hay pronósticos registrados: la tarea diaria los guarda antes de cada partido.</div>`;

  // Precisión en vivo
  if (R.n) {
    $("#acc-sub").textContent = `${R.n} pronósticos liquidados: acertó ${pct(R.hit, 1)} cuando esperaba ${pct(R.expected, 1)}.`;
    $("#acc-empty").innerHTML = "";
    chart("ch-reliable", () => ({
      type: "bar",
      data: { labels: R.bins.map((b) => b.range), datasets: [
        { label: "Esperado", data: R.bins.map((b) => b.expected * 100), backgroundColor: css("--official"), borderRadius: 4, maxBarThickness: 22 },
        { label: "Real", data: R.bins.map((b) => b.hit * 100), backgroundColor: css("--model"), borderRadius: 4, maxBarThickness: 22 },
      ] },
      options: baseOptions({
        plugins: { ...baseOptions().plugins, tooltip: { ...baseOptions().plugins.tooltip, callbacks: {
          label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(0)}%`, footer: (i) => `${R.bins[i[0].dataIndex].n} pronósticos` } } },
        scales: { ...baseOptions().scales, y: { ...baseOptions().scales.y, min: 0, max: 100, ticks: { ...baseOptions().scales.y.ticks, callback: (v) => v + "%" } } },
      }),
    }));
  } else {
    $("#ch-reliable").closest(".chart").style.display = "none";
    $("#acc-empty").innerHTML = `<div class="empty">La precisión se mide al terminar los partidos de los pronósticos registrados
      (${R.pending || 0} pendientes).</div>`;
  }

  // Ajuste automático
  const c = d.calibration || {};
  const T = c.T ?? 1;
  const verb = Math.abs(T - 1) < 0.005 ? "sin ajuste todavía" : T > 1 ? "suaviza: estaba demasiado segura" : "agudiza: estaba demasiado tímida";
  const hist = (c.history || []).slice(-30);
  $("#calib-box").innerHTML = `<div class="kv">
      <div><span>Temperatura actual</span><b class="num">${num(T, 3)}</b></div>
      <div><span>Partidos usados</span><b class="num">${(c.n || 0).toLocaleString("es-CL")}</b></div>
      <div><span>Efecto</span><b style="font-size:13px">${verb}</b></div>
      <div><span>Log loss antes → después</span><b class="num" style="font-size:13px">${c.ll_before != null ? `${num(c.ll_before, 3)} → ${num(c.ll_after, 3)}` : "–"}</b></div>
    </div>
    <p class="sub" style="margin:10px 0 0">El ajuste se acerca al valor medido a medida que hay más resultados (a los ${300} partidos pesa la mitad).
      ${hist.length > 1 ? `Últimos ${hist.length} días: ${hist.map((h) => num(h.T, 2)).join(" · ")}` : ""}</p>`;
  return d;
}
