"use strict";
/* Componentes de vistas: navegación secundaria, fichas y listas progresivas sin dependencias. */
let recordFilter = "all";
let viewTableId = 0;
function priceVerdict(option) {
  return option && option.p_fair != null ? option.verdict
    : { level: "none", label: "Sin referencia Pinnacle", reason: "Probabilidad orientativa; no acredita una ventaja de precio." };
}
function compactProb(p) {
  return `<dl class="compact-prob">${["Local", "Empate", "Visita"].map((label, i) =>
    `<div><dt>${label}</dt><dd>${p ? pct(p[i]) : "—"}</dd></div>`).join("")}</dl>`;
}
function priceAdvantage(m) {
  const all = m.pro || [], eligible = all.filter(o => o.bet);
  const o = (eligible.length ? eligible : all).reduce((best, x) => !best || x.edge > best.edge ? x : best, null);
  const bank = getBank();
  const scope = m.model_name?.includes("selecciones") ? "Solo consulta; sin registro en papel." : "Seguimiento en papel.";
  const registered = (cache["/api/suggestions"]?.ledger?.items || []).some(i => `m:${i.match_id}` === m.ref);
  const content = o ? `<dl class="price-facts">
    <div><dt>Selección</dt><dd>${esc({ "1": "Local", X: "Empate", "2": "Visita" }[o.key] || o.sel)}</dd></div>
    <div><dt>Cuota · ${esc(o.book)}</dt><dd>${num(o.odds)}</dd></div>
    <div><dt>Precio justo · Pinnacle</dt><dd>${num(o.fair_odds)}</dd></div>
    <div><dt>Ventaja</dt><dd>${signed(o.edge)}</dd></div>
    <div><dt>Monto sugerido sobre ${clp(bank)}</dt><dd>${clp(bank * (o.bet ? o.stake : 0))}</dd></div></dl>
    <span class="pill ${o.bet ? "good" : "warn"}">${o.bet ? "Con ventaja según la regla" : "Sin ventaja que cumpla la regla"}</span>`
    : '<p>Sin referencia de Pinnacle: no se evalúa una ventaja de precio ni un monto sugerido.</p>';
  return `<section class="mc-sec price-advantage"><h4>Ventaja de precio</h4>${content}
    <p class="mc-note">¼ de Kelly · tope 2 % por apuesta (${clp(bank * .02)}) · máximo diario 10 %. ${scope}</p>
    <a class="paper-link" href="#resultados" ${registered ? "" : "hidden"}>Ver apuesta registrada en Seguimiento</a></section>`;
}
function updateSecondaryNav(key, group) {
  document.querySelectorAll(".nav-subsections").forEach(box => {
    box.hidden = box.dataset.parent !== group;
    box.querySelectorAll("a").forEach(a => {
      const active = a.hash === "#" + key;
      a.classList.toggle("active", active);
      if (active) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  });
}
function decorateViewLists() {
  const ids = ["semaforo", "rel-today", "sg-closest", "sg-record", "rel-record", "trk-table", "trk-bets", "bt-leagues", "cb-strategies", "cb-patterns"];
  const boxes = new Set(ids.map(id => document.getElementById(id)).filter(Boolean));
  document.querySelectorAll(".table-wrap > table").forEach(table => {
    const box = table.parentElement;
    if (!box.id) box.id = `view-table-${++viewTableId}`;
    boxes.add(box);
  });
  for (const box of boxes) {
    const table = box.querySelector("table"); if (!table) continue;
    table.classList.add("record-table");
    const labels = [...table.querySelectorAll("thead th")].map(h => h.textContent.trim());
    const rows = [...table.querySelectorAll("tbody > tr")];
    const entries = rows.filter(row => !row.classList.contains("why-row") && !row.classList.contains("opt-group"));
    const filtered = entries.filter(row => !box.closest("#v-resultados") || recordFilter === "all" || row.dataset.result === recordFilter);
    const positions = new Map(filtered.map((row, i) => [row, i]));
    rows.forEach(row => {
      [...row.cells].forEach((cell, i) => cell.dataset.label = row.classList.contains("why-row") ? "Motivo" : labels[i] || "Detalle");
      const entry = row.classList.contains("why-row") ? row.previousElementSibling : row;
      row.hidden = !positions.has(entry) || (!box.dataset.expanded && positions.get(entry) >= 10);
    });
    let group = null;
    rows.forEach(row => {
      if (row.classList.contains("opt-group")) { group = row; group.hidden = true; }
      else if (group && !row.hidden) group.hidden = false;
    });
    listExpansion(box, filtered.length);
  }
  for (const id of ["matches", "cb-matches"]) {
    const box = document.getElementById(id); if (!box) continue;
    const rows = [...box.querySelectorAll(id === "matches" ? ".mrow,.rrow" : "details.mx")];
    rows.forEach((row, i) => {
      row.hidden = !box.dataset.expanded && i >= 10 && !row.classList.contains("open") && !row.open;
      if (row.nextElementSibling?.classList.contains("mdetail")) row.nextElementSibling.hidden = row.hidden;
    });
    box.querySelectorAll(".lg-block").forEach(group => group.hidden = ![...group.querySelectorAll(".mrow,.rrow")].some(r => !r.hidden));
    listExpansion(box, rows.length);
  }
}
function listExpansion(box, count) {
  let button = document.querySelector(`[data-expand-list="${box.id}"]`);
  if (!button && count > 10) {
    button = document.createElement("button"); button.type = "button"; button.className = "chip list-expand";
    button.dataset.expandList = box.id; box.after(button);
    button.onclick = () => { if (box.dataset.expanded) delete box.dataset.expanded; else box.dataset.expanded = "true"; decorateViewLists(); };
  }
  if (button) { button.hidden = count <= 10; button.textContent = box.dataset.expanded ? "Mostrar diez" : `Ver todas (${count})`; }
}
function initViewComponents() {
  const dialog = $("#match-filters"), slot = $("#match-filter-slot"), toolbar = $("#match-toolbar");
  const mobile = matchMedia("(max-width: 860px)");
  const position = () => {
    if (!mobile.matches && dialog.open) dialog.close();
    (mobile.matches ? $("#match-filter-body") : slot).append(toolbar);
  };
  position(); mobile.addEventListener("change", position);
  $("#match-filter-open").onclick = () => { dialog.showModal(); document.body.classList.add("filters-open"); };
  dialog.addEventListener("close", () => document.body.classList.remove("filters-open"));
  $("#match-filter-close").onclick = () => dialog.close();
  $("#tracking-filters").onclick = e => {
    const button = e.target.closest("[data-result-filter]"); if (!button) return;
    recordFilter = button.dataset.resultFilter;
    $("#tracking-filters").querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b === button)));
    decorateViewLists();
  };
  window.addEventListener("footy-bank-changed", () => {
    document.querySelectorAll("#matches .mdetail").forEach(detail => {
      const ref = detail.previousElementSibling.dataset.ref;
      const match = (cache["/api/upcoming"] || []).find(m => m.ref === ref);
      if (match) detail.querySelector(".price-advantage").outerHTML = priceAdvantage(match);
    });
  });
  const watched = "#matches,#cb-matches,#semaforo,#rel-today,#sg-closest,#sg-record,#rel-record,#trk-table,#trk-bets,#bt-leagues,#cb-strategies,#cb-patterns";
  const observer = new MutationObserver(changes => {
    if (!changes.some(c => c.target.closest(watched + ",.table-wrap,#sim-out,#ticket"))) return;
    observer.disconnect(); decorateViewLists(); observer.observe($("#main"), { childList: true, subtree: true });
  });
  observer.observe($("#main"), { childList: true, subtree: true });
}
