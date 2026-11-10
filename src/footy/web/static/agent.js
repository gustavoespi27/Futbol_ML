"use strict";
/* Capa agéntica en el dashboard: resumen del día (#agent-brief), chat flotante y preferencias del usuario.
   Consume /api/agent/* (src/footy_agents). Contrato SSE: tool_start, tool_result, token, done, error. */

const AGENT_USER = "default";

/* ---------- lector SSE unificado (chat por POST, resumen por GET) ---------- */
// EventSource no admite POST, así que se lee el cuerpo de fetch y se separa en eventos (bloques terminados en \n\n).
async function agentStream(path, { body, signal, on }) {
  const opts = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal }
    : { signal };
  const r = await fetch(path, opts);
  if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder("utf-8");
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let cut;
    while ((cut = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, cut);
      buf = buf.slice(cut + 2);
      let event = "message", data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (on[event]) on[event](data ? JSON.parse(data) : {});
    }
  }
}

// Texto del modelo -> HTML seguro: se escapa todo y solo se interpretan **negrita** y saltos de línea.
const agentText = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>");

const TOOL_LABELS = {
  create_watch: "Crear vigilancia", list_watches: "Vigilancias", cancel_watch: "Cancelar vigilancia", add_favorite: "Favoritos",
  get_stake_limits: "Límites de exposición",
  get_upcoming_matches: "Próximos partidos", get_value_bets: "Apuestas con valor", simulate_match: "Simulación",
  get_league_standings: "Tabla de posiciones", get_system_performance: "Rendimiento del sistema",
  find_team: "Búsqueda del equipo", analyze_match: "Análisis del partido", get_coverage: "Cobertura de datos",
  get_team_form: "Forma del equipo",
};
/* Pasos de decisión del agente (evento SSE `step`): qué observó y por qué cambió de camino. */
const STEP_ICONS = { observation: "◉", deviation: "↪", recovery: "↻", repair: "✎", policy: "⛔" };

/* ---------- resumen del día ---------- */
let briefCtl = null;
window.addEventListener("footy-data-paused", () => { if (briefCtl) briefCtl.abort(); });
window.addEventListener("hashchange", () => {
  if (!$("#v-inicio").classList.contains("active") && briefCtl) briefCtl.abort();
});
async function loadBriefing() {
  const box = $("#agent-brief");
  if (!box || !$("#v-inicio").classList.contains("active")) return;
  const body = $(".brief-body", box), foot = $(".brief-foot", box);
  if (briefCtl) briefCtl.abort();
  briefCtl = new AbortController();
  const controller = briefCtl;
  let text = "";
  body.classList.add("typing");
  body.innerHTML = `<span class="skeleton" style="width:92%"></span><span class="skeleton" style="width:70%"></span>`;
  foot.textContent = "Preparando tu resumen…";
  try {
    await loadSystemStatus();
    if (systemState.kind !== "fresh" || controller !== briefCtl) return;
    const list = await api("/api/upcoming");
    if (!list.length) { gateView($("#v-inicio"), "no_matches"); return; }
    const suggestions = await api("/api/suggestions");
    if (systemState.kind !== "fresh" || controller !== briefCtl) return;
    if (!suggestions.n_matches_sharp) {
      const coverage = FootyTrust.coverage(list);
      body.textContent = `Calendario: ${coverage.label}. ${FootyTrust.partidos(coverage.missing)} aún sin cuotas de referencia para evaluar su ventaja.`;
      foot.textContent = "Resumen automático (sin IA)";
      return;
    }
    await agentStream(`/api/agent/briefing?user_id=${AGENT_USER}`, { signal: controller.signal, on: {
      token: (d) => { text += d.delta; body.innerHTML = agentText(text); },
      error: (d) => { foot.textContent = d.error; },
      done: (d) => {
        foot.textContent = FootyTrust.briefingLabel(d);
      },
    } });
  } catch (e) {
    if (e.name === "AbortError") return;
    trustEmpty(body, "error", { action: loadBriefing });
    foot.textContent = "";
  } finally {
    if (controller === briefCtl) body.classList.remove("typing");
  }
}

/* ---------- chat flotante ---------- */
const chat = { open: false, busy: false };
let chatReturnFocus = null;
function chatEl(sel) { return $(sel, $("#agent-chat")); }

function toggleChat(force) {
  if ((force ?? !chat.open) && !chat.open) chatReturnFocus = document.activeElement;
  chat.open = force ?? !chat.open;
  $("#agent-chat").hidden = !chat.open;
  $("#agent-fab").setAttribute("aria-expanded", String(chat.open));
  $("#more-assistant").setAttribute("aria-expanded", String(chat.open));
  if (chat.open) chatEl("textarea").focus();
  else (chatReturnFocus && chatReturnFocus.getClientRects().length ? chatReturnFocus : $("#agent-fab")).focus();
  if (chat.open) loadAgentActivity();
}

function chatBubble(role, html = "") {
  const log = chatEl(".chat-log");
  log.insertAdjacentHTML("beforeend", `<div class="msg ${role}"><div class="msg-tools"></div><div class="msg-text">${html}</div></div>`);
  log.scrollTop = log.scrollHeight;
  return log.lastElementChild;
}

async function sendChat(message) {
  message = message.trim();
  if (!message || chat.busy) return;
  chat.busy = true;
  const form = chatEl("form"), ta = chatEl("textarea");
  form.classList.add("busy");
  ta.value = "";
  chatEl(".chat-suggest").hidden = true;
  chatBubble("user", agentText(message));
  const msg = chatBubble("bot");
  const tools = $(".msg-tools", msg), out = $(".msg-text", msg), log = chatEl(".chat-log");
  out.textContent = "Consultando…";
  out.classList.add("typing");
  let text = "";
  const scroll = () => { log.scrollTop = log.scrollHeight; };
  try {
    await agentStream("/api/agent/chat", { body: { message, user_id: AGENT_USER }, on: {
      tool_start: (d) => {
        tools.insertAdjacentHTML("beforeend", `<span class="tool-badge run" data-tool="${esc(d.tool)}">
          <i class="spin" aria-hidden="true"></i>${esc(TOOL_LABELS[d.tool] || d.tool)}</span>`);
        scroll();
      },
      tool_result: (d) => {
        const b = [...tools.querySelectorAll(`.tool-badge.run[data-tool="${CSS.escape(d.tool)}"]`)].pop();
        if (!b) return;
        b.className = `tool-badge ${d.success ? "ok" : "fail"}`;
        b.title = `${d.summary} · ${Math.round(d.elapsed_ms)} ms`;
        b.querySelector(".spin").outerHTML = d.success ? "✓ " : "✕ ";
      },
      step: (d) => {
        tools.insertAdjacentHTML("beforeend", `<span class="agent-step ${esc(d.kind)}"><i aria-hidden="true">${
          STEP_ICONS[d.kind] || "•"}</i>${esc(d.text)}</span>`);
        scroll();
      },
      token: (d) => { text += d.delta; out.innerHTML = agentText(text); scroll(); },
      error: (d) => {
        if (!text) out.textContent = "";
        out.insertAdjacentHTML("beforeend", `<p class="msg-err">${esc(d.error)}</p>`);
      },
    } });
  } catch (e) {
    if (!text) out.textContent = "";
    out.insertAdjacentHTML("beforeend", `<p class="msg-err">No se pudo contactar al asistente (${esc(e.message)}).</p>`);
  } finally {
    out.classList.remove("typing");
    chat.busy = false;
    form.classList.remove("busy");
    ta.focus();
    loadAgentActivity();
  }
}

/* ---------- alertas y bitácora: solo lecturas, no disparan el vigía ni el LLM ---------- */
let activityBusy = false;
let activityQueued = false;
let activityUnread = 0;
const WATCH_LABELS = { kickoff_soon: "Inicio cercano", pinnacle_available: "Precio Pinnacle disponible",
  value_appears: "Aparece ventaja", value_disappears: "Desaparece ventaja", line_move: "Movimiento de línea",
  probability_shift: "Cambio de probabilidad", coverage_lost: "Cobertura perdida" };
function activityTime(value) {
  return new Intl.DateTimeFormat("es-CL", { timeZone: "America/Santiago", dateStyle: "short", timeStyle: "short" })
    .format(new Date(value));
}
async function loadAgentActivity() {
  if (document.hidden) return;
  if (activityBusy) { activityQueued = true; return; }
  activityBusy = true;
  const query = `user_id=${encodeURIComponent(AGENT_USER)}`;
  const get = async (path) => { const r = await fetch(path); if (!r.ok) throw Error(`HTTP ${r.status}`); return r.json(); };
  try {
    const alerts = await get(`/api/agent/alerts?${query}&unread=true`);
    const badge = $("#agent-alert-badge");
    badge.textContent = alerts.length ? String(alerts.length) : "";
    badge.hidden = !alerts.length;
    $("#agent-fab").setAttribute("aria-label", `Abrir Asistente${alerts.length ? `, ${alerts.length} alertas sin leer` : ""}`);
    $("#agent-alerts-body").innerHTML = alerts.length ? alerts.map((a) => `<article class="agent-alert">
      <strong>${esc(WATCH_LABELS[a.kind] || a.kind)}</strong><p>${esc(a.text)}</p>
      <small>${esc(activityTime(a.created_at))}</small><button type="button" data-read-alert="${a.id}">Marcar leída</button>
      </article>`).join("") : `<p class="agent-activity-empty">No hay alertas sin leer.</p>`;
    if (alerts.length > activityUnread) $("#agent-alerts").open = true;
    activityUnread = alerts.length;
    if (chat.open) {
      const [runs, watches] = await Promise.all([get(`/api/agent/runs?${query}&limit=5`),
        get(`/api/agent/watch-log?${query}&limit=5`)]);
      const renderRun = (r) => `<details class="agent-run" data-run-key="chat-${r.id}"><summary>Chat · ${esc(activityTime(r.started_at))}
        · ${r.success ? "Completado" : "Con incidencias"}</summary><p>${esc(r.message)}</p><ol>${r.steps.map((s) =>
        `<li>${esc(TOOL_LABELS[s.detail] || s.detail)}${s.summary ? ` · ${esc(s.summary)}` : ""}${s.reason ? ` · ${esc(s.reason)}` : ""}</li>`).join("")}</ol></details>`;
      const renderWatch = (r) => `<details class="agent-run" data-run-key="watch-${r.id}"><summary>Vigía · ${esc(activityTime(r.run_at))}
        · ${r.perceived} partidos · ${r.actions} acciones</summary>
        <details><summary>Percepción del calendario</summary><ul>${Object.values(r.perception || {}).map((s) =>
        `<li>${esc(s.home)} vs ${esc(s.away)} · ${s.has_pinnacle ? "con Pinnacle" : "sin Pinnacle"}
        · ${s.value ? "con ventaja elegible" : "sin ventaja elegible"} · ${esc(s.source)}</li>`).join("")}</ul></details>
        <ul>${r.decisions.map((d) =>
        `<li><b>${d.selected ? "Actuar" : "Descartar"}</b> · ${esc(WATCH_LABELS[d.kind] || d.kind)}${d.match_id ? ` · partido ${d.match_id}` : ""}:
        ${esc(d.reason)}</li>`).join("")}</ul></details>`;
      const expanded = new Set([...document.querySelectorAll(".agent-run[open]")].map(el => el.dataset.runKey));
      const scrollTop = chatEl(".agent-activity").scrollTop;
      const focusedRun = document.activeElement?.closest("[data-run-key]")?.dataset.runKey;
      $("#agent-runs-body").innerHTML = watches.map(renderWatch).join("") + runs.map(renderRun).join("")
        || `<p class="agent-activity-empty">Aún no hay ejecuciones.</p>`;
      for (const details of document.querySelectorAll(".agent-run")) {
        details.open = expanded.has(details.dataset.runKey);
        if (details.dataset.runKey === focusedRun) details.querySelector("summary").focus({preventScroll:true});
      }
      chatEl(".agent-activity").scrollTop = scrollTop;
    }
    $("#agent-activity-status").textContent = "";
  } catch (e) {
    $("#agent-activity-status").textContent = "No se pudo actualizar la actividad. Reintenta con Actualizar actividad.";
  } finally {
    activityBusy = false;
    if (activityQueued) { activityQueued = false; loadAgentActivity(); }
  }
}

function initAgentActivity() {
  $("#agent-fab").insertAdjacentHTML("beforeend", `<span id="agent-alert-badge" class="agent-alert-badge" hidden aria-hidden="true"></span>`);
  chatEl(".chat-head").insertAdjacentHTML("afterend", `<section class="agent-activity" aria-label="Alertas y bitácora del agente">
    <div class="agent-activity-actions"><button type="button" id="agent-activity-refresh">${REFRESH_ICON}Actualizar actividad</button>
    <span id="agent-activity-status" role="status"></span></div>
    <details id="agent-alerts"><summary>Alertas sin leer</summary><div id="agent-alerts-body"></div></details>
    <details id="agent-runs"><summary>Bitácora del agente</summary><div id="agent-runs-body"></div></details></section>`);
  $("#agent-activity-refresh").addEventListener("click", (event) => spinWhile(event.currentTarget, loadAgentActivity));
  $("#agent-alerts-body").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-read-alert]");
    if (!button) return;
    button.disabled = true;
    try {
      const r = await fetch(`/api/agent/alerts/${button.dataset.readAlert}/read`, {method:"POST",
        headers:{"Content-Type":"application/json"}, body:JSON.stringify({user_id:AGENT_USER})});
      if (!r.ok) throw Error(`HTTP ${r.status}`);
      await loadAgentActivity();
      $("#agent-alerts > summary").focus();
    } catch (e) { button.disabled = false; $("#agent-activity-status").textContent = "No se pudo marcar la alerta. Reintenta."; }
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) loadAgentActivity(); });
  setInterval(loadAgentActivity, 30000);
  loadAgentActivity();
}

/* ---------- preferencias ---------- */
let prefs = null;
async function openPrefs() {
  const dlg = $("#agent-prefs");
  const [p, catalog, upcoming] = await Promise.all([
    fetch(`/api/agent/preferences?user_id=${AGENT_USER}`).then((r) => r.json()),
    api("/api/league-catalog"), api("/api/upcoming").catch(() => []),
  ]);
  prefs = p;
  const leagues = catalog.filter((l) => l.n > 0 || p.favorite_leagues.includes(l.code));
  $("#pref-leagues").innerHTML = leagues.map((l) => `<button type="button" class="chip ${p.favorite_leagues.includes(l.code) ? "on" : ""}"
    data-code="${esc(l.code)}" aria-pressed="${p.favorite_leagues.includes(l.code)}">${leagueLogo(l.code, 14)}${esc(l.name)}</button>`).join("");
  const names = [...new Set(upcoming.flatMap((m) => [m.home, m.away]))].sort((a, b) => a.localeCompare(b, "es"));
  $("#pref-team-list").innerHTML = names.map((n) => `<option value="${esc(n)}">`).join("");
  renderPrefTeams();
  dlg.querySelector(`input[name=risk][value=${p.risk_profile}]`).checked = true;
  dlg.showModal();
}

function renderPrefTeams() {
  $("#pref-teams").innerHTML = prefs.favorite_teams.map((t, i) => `<span class="pill">${esc(t)}
    <button type="button" class="pill-x" data-i="${i}" aria-label="Quitar ${esc(t)}">×</button></span>`).join("")
    || `<span class="pref-empty">Sin equipos favoritos todavía.</span>`;
}

function addPrefTeam() {
  const inp = $("#pref-team-input"), name = inp.value.trim();
  if (name && !prefs.favorite_teams.some((t) => t.toLowerCase() === name.toLowerCase())) prefs.favorite_teams.push(name);
  inp.value = "";
  renderPrefTeams();
}

async function savePrefs(ev) {
  ev.preventDefault();
  const dlg = $("#agent-prefs");
  prefs.favorite_leagues = [...$("#pref-leagues").querySelectorAll(".chip.on")].map((c) => c.dataset.code);
  prefs.risk_profile = dlg.querySelector("input[name=risk]:checked").value;
  const r = await fetch("/api/agent/preferences", { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(prefs) });
  if (!r.ok) { $("#pref-status").textContent = "No se pudieron guardar las preferencias."; return; }
  dlg.close();
  rendered.delete("inicio");
  if ($("#v-inicio").classList.contains("active")) route();
}

/* ---------- arranque ---------- */
function initAgent() {
  initAgentActivity();
  $("#agent-fab").addEventListener("click", () => toggleChat());
  chatEl(".chat-close").addEventListener("click", () => toggleChat(false));
  $("#agent-chat").addEventListener("keydown", (e) => { if (e.key === "Escape") toggleChat(false); });
  chatEl("form").addEventListener("submit", (e) => { e.preventDefault(); sendChat(chatEl("textarea").value); });
  // Enter envía; Shift+Enter hace salto de línea
  chatEl("textarea").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(e.target.value); }
  });
  chatEl(".chat-suggest").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b) sendChat(b.textContent);
  });

  $("#brief-refresh").addEventListener("click", (event) => spinWhile(event.currentTarget, loadBriefing));
  $("#brief-prefs").addEventListener("click", () => openPrefs().catch((e) => {
    $("#agent-brief .brief-foot").textContent = `No se pudieron abrir las preferencias (${e.message}).`;
  }));
  $("#pref-form").addEventListener("submit", savePrefs);
  $("#pref-cancel").addEventListener("click", () => $("#agent-prefs").close());
  $("#pref-leagues").addEventListener("click", (e) => {
    const c = e.target.closest(".chip");
    if (!c) return;
    c.classList.toggle("on");
    c.setAttribute("aria-pressed", String(c.classList.contains("on")));
  });
  $("#pref-team-add").addEventListener("click", addPrefTeam);
  $("#pref-team-input").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addPrefTeam(); } });
  $("#pref-teams").addEventListener("click", (e) => {
    const x = e.target.closest(".pill-x");
    if (!x) return;
    prefs.favorite_teams.splice(+x.dataset.i, 1);
    renderPrefTeams();
  });

}
initAgent();
