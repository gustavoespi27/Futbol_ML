"use strict";
/* Capa agéntica en el dashboard: resumen del día (#agent-brief), chat con el Míster, su historial de
   conversaciones, lo que aprendió del usuario y las preferencias. Consume /api/agent/* (src/footy_agents).
   El chat muestra solo la respuesta: los pasos internos (herramientas, desvíos, reparaciones) quedan en el registro
   del servidor, no en pantalla. */

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

/* ---------- chat con el Míster ---------- */
const chat = { open: false, busy: false, conversationId: null, historyOpen: false, stick: true };
let chatReturnFocus = null;
const CHAT_KEY = "mister-conversation";
const CHAT_GREETING = "Aquí el Míster. En este equipo los números mandan, no la camiseta. Pregúntame por un partido, "
  + "la tabla, cómo llega un equipo o si hay alguna cuota con valor.";
function chatEl(sel) { return $(sel, $("#agent-chat")); }
const agentApi = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw Error(`HTTP ${r.status}`);
  return r.status === 204 ? null : r.json();
};
const userQuery = `user_id=${encodeURIComponent(AGENT_USER)}`;

function toggleChat(force) {
  if ((force ?? !chat.open) && !chat.open) chatReturnFocus = document.activeElement;
  chat.open = force ?? !chat.open;
  $("#agent-chat").hidden = !chat.open;
  $("#agent-fab").setAttribute("aria-expanded", String(chat.open));
  $("#more-assistant").setAttribute("aria-expanded", String(chat.open));
  if (chat.open) { chatEl("textarea").focus(); scrollChat({ force: true, smooth: false }); }
  else (chatReturnFocus && chatReturnFocus.getClientRects().length ? chatReturnFocus : $("#agent-fab")).focus();
}

function chatBubble(role, html = "") {
  const log = chatEl(".chat-log");
  log.insertAdjacentHTML("beforeend", `<div class="msg ${role}"><div class="msg-text">${html}</div></div>`);
  return log.lastElementChild;
}

/* Desplazamiento: el chat sigue la conversación mientras el usuario está abajo; si sube a leer, no lo mueve y
   aparece el botón para volver a la última consulta (con un punto si llegó algo nuevo mientras tanto). */
const NEAR_BOTTOM = 80;
function chatNearBottom() {
  const log = chatEl(".chat-log");
  return log.scrollHeight - log.scrollTop - log.clientHeight < NEAR_BOTTOM;
}
function scrollChat({ force = false, smooth = true } = {}) {
  const log = chatEl(".chat-log");
  if (!force && !chat.stick) { $("#chat-jump").classList.add("has-new"); return; }
  chat.stick = true;
  const animate = smooth && !matchMedia("(prefers-reduced-motion: reduce)").matches;
  chat.autoUntil = animate ? Date.now() + 700 : 0;   // el desplazamiento suave no cuenta como «el usuario subió»
  log.scrollTo({ top: log.scrollHeight, behavior: animate ? "smooth" : "auto" });
}
function updateJump() {
  if (Date.now() < (chat.autoUntil || 0) && !chatNearBottom()) return;
  chat.stick = chatNearBottom();
  const jump = $("#chat-jump");
  jump.hidden = chat.stick;
  if (chat.stick) jump.classList.remove("has-new");
}

function resetChatLog() {
  chatEl(".chat-log").innerHTML = "";
  chatBubble("bot", agentText(CHAT_GREETING));
  chatEl(".chat-suggest").hidden = false;
}

function setConversation(id) {
  chat.conversationId = id;
  try { id ? localStorage.setItem(CHAT_KEY, String(id)) : localStorage.removeItem(CHAT_KEY); } catch (e) { /* sin storage */ }
}

function newConversation() {
  if (chat.busy) return;
  setConversation(null);
  resetChatLog();
  toggleHistory(false);
  chatEl("textarea").focus();
}

async function openConversation(id, { quiet = false } = {}) {
  try {
    const msgs = await agentApi(`/api/agent/conversations/${id}?${userQuery}`);
    chatEl(".chat-log").innerHTML = "";
    chatBubble("bot", agentText(CHAT_GREETING));
    for (const m of msgs) chatBubble(m.role === "user" ? "user" : "bot", agentText(m.content));
    chatEl(".chat-suggest").hidden = msgs.length > 0;
    scrollChat({ force: true, smooth: false });
    setConversation(id);
    toggleHistory(false);
  } catch (e) {
    setConversation(null);
    if (!quiet) $("#chat-history-status").textContent = "No se pudo abrir la conversación.";
  }
}

async function sendChat(message) {
  message = message.trim();
  if (!message || chat.busy) return;
  chat.busy = true;
  misterThinking(true);
  toggleHistory(false);
  const form = chatEl("form"), ta = chatEl("textarea");
  form.classList.add("busy");
  ta.value = "";
  chatEl(".chat-suggest").hidden = true;
  chatBubble("user", agentText(message));
  const msg = chatBubble("bot");
  const out = $(".msg-text", msg);
  out.innerHTML = `<span class="msg-thinking">El Míster está revisando la pizarra<i></i><i></i><i></i></span>`;
  scrollChat({ force: true });                      // al preguntar se baja de inmediato para ver que está pensando
  let text = "";
  const scroll = () => scrollChat();
  try {
    if (!chat.conversationId) {
      const created = await agentApi("/api/agent/conversations", { method: "POST", body: JSON.stringify({ user_id: AGENT_USER }) });
      setConversation(created.id);
    }
    await agentStream("/api/agent/chat", { body: { message, user_id: AGENT_USER, conversation_id: chat.conversationId }, on: {
      token: (d) => { text += d.delta; out.innerHTML = agentText(text); scroll(); },
      error: (d) => {
        if (!text) out.textContent = "";
        out.insertAdjacentHTML("beforeend", `<p class="msg-err">${esc(d.error)}</p>`);
        scroll();
      },
    } });
    if (!text && !out.querySelector(".msg-err")) {
      out.textContent = "No tengo una respuesta para eso. Prueba preguntándolo de otra forma.";
      scroll();
    }
  } catch (e) {
    out.innerHTML = `<p class="msg-err">No se pudo contactar al Míster (${esc(e.message)}).</p>`;
    scroll();
  } finally {
    chat.busy = false;
    misterThinking(false);
    form.classList.remove("busy");
    ta.focus();
  }
}

/* ---------- historial de conversaciones y lo que el Míster sabe del usuario ---------- */
const MEMORY_LABELS = {
  team: (i) => i.stated ? `Hincha de ${i.label}` : `Consultas seguido a ${i.label}`,
  league: (i) => `Te interesa ${i.label}`,
  topic: (i) => `Sueles preguntar por ${i.label}`,
};
const chatWhen = (value) => {
  const d = new Date(value), today = new Date();
  const opts = d.toDateString() === today.toDateString() ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }
    : { day: "numeric", month: "short" };
  return new Intl.DateTimeFormat("es-CL", { timeZone: "America/Santiago", ...opts }).format(d);
};

function toggleHistory(open = !chat.historyOpen) {
  chat.historyOpen = open;
  chatEl(".chat-history").hidden = !open;
  $("#chat-history-btn").setAttribute("aria-expanded", String(open));
  $("#chat-history-btn").classList.toggle("on", open);
  if (open) loadHistory();
}

async function loadHistory() {
  const status = $("#chat-history-status");
  status.textContent = "";
  try {
    const [convs, memory] = await Promise.all([agentApi(`/api/agent/conversations?${userQuery}`),
      agentApi(`/api/agent/profile?${userQuery}`)]);
    $("#chat-history-list").innerHTML = convs.map((c) => `<li class="${c.id === chat.conversationId ? "current" : ""}">
        <button type="button" class="history-open" data-conv="${c.id}"><b>${esc(c.title)}</b>
          <small>${esc(chatWhen(c.updated_at))} · ${c.messages} ${c.messages === 1 ? "pregunta" : "preguntas"}</small></button>
        <button type="button" class="history-del" data-conv-del="${c.id}" aria-label="Borrar «${esc(c.title)}»">×</button></li>`).join("")
      || `<li class="history-empty">Aún no hay conversaciones guardadas.</li>`;
    const shown = memory.filter((i) => i.stated || i.weight >= 2);
    $("#chat-memory-list").innerHTML = shown.map((i) => `<li class="${i.stated ? "stated" : ""}">
        <span>${esc(MEMORY_LABELS[i.kind](i))}</span>
        <button type="button" class="history-del" data-mem-del="${i.id}" aria-label="Olvidar: ${esc(MEMORY_LABELS[i.kind](i))}">×</button></li>`).join("")
      || `<li class="history-empty">Todavía no sé mucho de ti. Cuéntame qué equipo sigues.</li>`;
    $("#chat-memory-clear").disabled = !memory.length;
  } catch (e) {
    status.textContent = "No se pudo cargar el historial.";
  }
}

async function onHistoryClick(e) {
  const open = e.target.closest("[data-conv]"), del = e.target.closest("[data-conv-del]");
  const mem = e.target.closest("[data-mem-del]");
  try {
    if (open) await openConversation(Number(open.dataset.conv));
    else if (del) {
      const id = Number(del.dataset.convDel);
      await agentApi(`/api/agent/conversations/${id}?${userQuery}`, { method: "DELETE" });
      if (id === chat.conversationId) { setConversation(null); resetChatLog(); }
      await loadHistory();
    } else if (mem) {
      await agentApi(`/api/agent/profile/${mem.dataset.memDel}?${userQuery}`, { method: "DELETE" });
      await loadHistory();
    }
  } catch (err) {
    $("#chat-history-status").textContent = "No se pudo completar la acción. Reintenta.";
  }
}

function initChat() {
  resetChatLog();
  chatEl(".chat-log").addEventListener("scroll", updateJump, { passive: true });
  $("#chat-jump").addEventListener("click", () => { scrollChat({ force: true }); chatEl("textarea").focus({ preventScroll: true }); });
  let saved = null;
  try { saved = Number(localStorage.getItem(CHAT_KEY)) || null; } catch (e) { /* sin storage */ }
  if (saved) openConversation(saved, { quiet: true });
  $("#chat-history-btn").addEventListener("click", () => toggleHistory());
  $("#chat-new-btn").addEventListener("click", newConversation);
  $("#chat-history-new").addEventListener("click", newConversation);
  $("#chat-history").addEventListener("click", onHistoryClick);
  $("#chat-memory-clear").addEventListener("click", async () => {
    try { await agentApi(`/api/agent/profile?${userQuery}`, { method: "DELETE" }); await loadHistory(); }
    catch (e) { $("#chat-history-status").textContent = "No se pudo borrar la memoria. Reintenta."; }
  });
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
  dlg.querySelectorAll("input[name=alert-type]").forEach((box) => { box.checked = p.alert_types.includes(box.value); });
  $("#pref-alerts-favorites").checked = !!p.alerts_only_favorites;
  $("#pref-browser-notify").checked = !!p.browser_notifications;
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
  prefs.alert_types = [...dlg.querySelectorAll("input[name=alert-type]:checked")].map((box) => box.value);
  prefs.alerts_only_favorites = $("#pref-alerts-favorites").checked;
  prefs.browser_notifications = $("#pref-browser-notify").checked;
  if (prefs.browser_notifications && "Notification" in window && Notification.permission === "default") {
    try { await Notification.requestPermission(); } catch (e) { /* sin permiso: el panel de avisos sigue igual */ }
  }
  const r = await fetch("/api/agent/preferences", { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(prefs) });
  if (!r.ok) { $("#pref-status").textContent = "No se pudieron guardar las preferencias."; return; }
  dlg.close();
  if (typeof alertsState !== "undefined") alertsState.browser = prefs.browser_notifications;
  rendered.delete("inicio");
  if ($("#v-inicio").classList.contains("active")) route();
}

/* ---------- arranque ---------- */
function initAgent() {
  initChat();
  $("#agent-fab").addEventListener("click", () => toggleChat());
  chatEl(".chat-close").addEventListener("click", () => toggleChat(false));
  $("#agent-chat").addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (chat.historyOpen) { toggleHistory(false); $("#chat-history-btn").focus(); } else toggleChat(false);
  });
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
