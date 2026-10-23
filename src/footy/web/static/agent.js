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
  get_upcoming_matches: "Próximos partidos", get_value_bets: "Apuestas con valor", simulate_match: "Simulación",
  get_league_standings: "Tabla de posiciones", get_system_performance: "Rendimiento del sistema",
};

/* ---------- resumen del día ---------- */
let briefCtl = null;
async function loadBriefing() {
  const box = $("#agent-brief");
  if (!box) return;
  const body = $(".brief-body", box), foot = $(".brief-foot", box);
  if (briefCtl) briefCtl.abort();
  briefCtl = new AbortController();
  let text = "";
  body.classList.add("typing");
  body.innerHTML = `<span class="skeleton" style="width:92%"></span><span class="skeleton" style="width:70%"></span>`;
  foot.textContent = "Preparando tu resumen…";
  try {
    await agentStream(`/api/agent/briefing?user_id=${AGENT_USER}`, { signal: briefCtl.signal, on: {
      token: (d) => { text += d.delta; body.innerHTML = agentText(text); },
      error: (d) => { foot.textContent = d.error; },
      done: (d) => {
        foot.textContent = !d.success ? "Resumen automático: la IA local no está disponible"
          : d.iterations === 0 ? "Resumen automático: nada destacado para tus preferencias en las próximas 24 h"
          : "Redactado por la IA local con datos del sistema";
      },
    } });
  } catch (e) {
    if (e.name === "AbortError") return;
    body.textContent = "No se pudo cargar el resumen.";
    foot.textContent = e.message;
  } finally {
    body.classList.remove("typing");
  }
}

/* ---------- chat flotante ---------- */
const chat = { open: false, busy: false };
function chatEl(sel) { return $(sel, $("#agent-chat")); }

function toggleChat(force) {
  chat.open = force ?? !chat.open;
  $("#agent-chat").hidden = !chat.open;
  $("#agent-fab").setAttribute("aria-expanded", String(chat.open));
  if (chat.open) chatEl("textarea").focus();
  else $("#agent-fab").focus();
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
      token: (d) => { text += d.delta; out.innerHTML = agentText(text); scroll(); },
      error: (d) => { out.insertAdjacentHTML("beforeend", `<p class="msg-err">${esc(d.error)}</p>`); },
    } });
  } catch (e) {
    out.insertAdjacentHTML("beforeend", `<p class="msg-err">No se pudo contactar al asistente (${esc(e.message)}).</p>`);
  } finally {
    out.classList.remove("typing");
    chat.busy = false;
    form.classList.remove("busy");
    ta.focus();
  }
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
  loadBriefing();
}

/* ---------- arranque ---------- */
function initAgent() {
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

  $("#brief-refresh").addEventListener("click", loadBriefing);
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

  loadBriefing();
}
initAgent();
