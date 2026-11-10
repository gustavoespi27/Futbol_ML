/* Avisos fuera del chat: campana en la barra superior con panel (escritorio) u hoja inferior (móvil).
   Consume /api/agent/alerts (vigía determinista, sin LLM). Opcional: Notification API del navegador mientras la
   pestaña está abierta, solo si el usuario lo activó en Preferencias. */

const ALERT_KINDS = {
  favorite_plays: { label: "Juega tu equipo", icon: "star" },
  value_bet: { label: "Cuota con valor", icon: "spark" },
  near_value: { label: "Cerca de tener valor", icon: "target" },
  value_combo: { label: "Combinada con valor", icon: "layers" },
  near_combo: { label: "Combinada cercana", icon: "layers" },
};
const ALERT_ICONS = {
  star: '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
  spark: '<path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  layers: '<path d="m12 2 9 5-9 5-9-5 9-5z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
};
const alertsState = { items: [], open: false, busy: false, known: null, browser: false };

const alertIcon = (kind) => `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
  stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ALERT_ICONS[(ALERT_KINDS[kind] || {}).icon || "eye"]}</svg>`;
const alertLabel = (kind) => (ALERT_KINDS[kind] || {}).label
  || `Vigilancia · ${(typeof WATCH_LABELS !== "undefined" && WATCH_LABELS[kind]) || kind}`;

const alertClock = new Intl.DateTimeFormat("es-CL", { timeZone: "America/Santiago", weekday: "short", day: "2-digit",
  month: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
function alertWhen(a) {
  if (a.facts.kickoff_local) return a.facts.kickoff_local.replace(" hora de Chile", "");
  return a.facts.kickoff ? alertClock.format(new Date(a.facts.kickoff)) : "";   // vigilancias anteriores al formato local
}

function renderAlerts() {
  const list = $("#alerts-list"), unread = alertsState.items.filter((a) => !a.read);
  const count = $("#alerts-count");
  count.textContent = unread.length > 9 ? "9+" : String(unread.length);
  count.hidden = !unread.length;
  $("#alerts-btn").setAttribute("aria-label", unread.length ? `Avisos, ${unread.length} sin leer` : "Avisos");
  $("#alerts-read-all").disabled = !unread.length;
  if (!alertsState.items.length) {
    list.innerHTML = `<div class="alerts-empty">${misterPose("alerts", 92)}<b>Sin avisos nuevos</b><span>Te avisaremos cuando juegue un equipo que
      sigues o aparezca una cuota que valga la pena frente a Pinnacle.</span></div>`;
    return;
  }
  list.innerHTML = alertsState.items.map((a) => `<article class="alert-item ${a.read ? "" : "unread"}" data-kind="${esc(a.kind)}">
      <span class="alert-ico">${alertIcon(a.kind)}</span>
      <div class="alert-body">
        <span class="alert-kind">${esc(alertLabel(a.kind))}${alertWhen(a) ? ` · ${esc(alertWhen(a))}` : ""}</span>
        <p>${esc(a.text)}</p>
        <div class="alert-actions">
          <button type="button" class="alert-open" data-alert-match="${a.match_id}">Ver partido</button>
          ${a.read ? "" : `<button type="button" class="alert-read" data-alert-read="${a.id}">Marcar leída</button>`}
        </div>
      </div></article>`).join("");
}

function notifyBrowser(items) {
  if (!alertsState.browser || !("Notification" in window) || Notification.permission !== "granted") return;
  for (const a of items.slice(0, 3)) {
    try { new Notification(`Fútbol ML · ${alertLabel(a.kind)}`, { body: a.text, tag: `alert-${a.id}` }); }
    catch (e) { /* el navegador puede bloquear notificaciones fuera de un gesto: el panel sigue disponible */ }
  }
}

async function loadAlerts() {
  if (alertsState.busy || document.hidden) return;
  alertsState.busy = true;
  try {
    const r = await fetch(`/api/agent/alerts?user_id=${encodeURIComponent(AGENT_USER)}`);
    if (!r.ok) throw Error(`HTTP ${r.status}`);
    const items = await r.json();
    const fresh = alertsState.known ? items.filter((a) => !a.read && !alertsState.known.has(a.id)) : [];
    alertsState.known = new Set(items.map((a) => a.id));
    alertsState.items = items;
    renderAlerts();
    $("#alerts-status").textContent = "";
    if (fresh.length) {
      const btn = $("#alerts-btn");
      btn.classList.remove("ringing"); void btn.offsetWidth; btn.classList.add("ringing");
      const coach = $(".alerts-mister .mister-pose");
      if (coach) { coach.classList.remove("hop"); void coach.offsetWidth; coach.classList.add("hop"); }
      notifyBrowser(fresh);
    }
  } catch (e) {
    $("#alerts-status").textContent = "No se pudieron cargar los avisos. Reintenta en un momento.";
  } finally { alertsState.busy = false; }
}

async function postAlert(path) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: AGENT_USER }) });
  if (!r.ok) throw Error(`HTTP ${r.status}`);
}

function toggleAlerts(open = !alertsState.open) {
  alertsState.open = open;
  const panel = $("#alerts-panel"), btn = $("#alerts-btn");
  panel.hidden = !open;
  btn.setAttribute("aria-expanded", String(open));
  document.body.classList.toggle("alerts-open", open);
  if (open) { loadAlerts(); (panel.querySelector(".alert-open") || $("#alerts-close")).focus(); }
  else btn.focus({ preventScroll: true });
}

function openAlertMatch(matchId) {
  toggleAlerts(false);
  homeMatchRef = `m:${matchId}`;
  matchSel = { type: "all" };
  matchDate = { type: "all" };
  if (location.hash === "#partidos") route(); else location.hash = "#partidos";
}

async function loadAlertPrefs() {
  try {
    const p = await (await fetch(`/api/agent/preferences?user_id=${encodeURIComponent(AGENT_USER)}`)).json();
    alertsState.browser = !!p.browser_notifications;
  } catch (e) { alertsState.browser = false; }
}

function initAlerts() {
  $("#alerts-btn").addEventListener("click", () => toggleAlerts());
  $("#alerts-close").addEventListener("click", () => toggleAlerts(false));
  $("#alerts-panel").addEventListener("keydown", (e) => { if (e.key === "Escape") toggleAlerts(false); });
  document.addEventListener("click", (e) => {
    if (alertsState.open && !e.target.closest("#alerts-panel, #alerts-btn")) toggleAlerts(false);
  });
  $("#alerts-list").addEventListener("click", async (e) => {
    const open = e.target.closest("[data-alert-match]");
    if (open) { openAlertMatch(open.dataset.alertMatch); return; }
    const read = e.target.closest("[data-alert-read]");
    if (!read) return;
    read.disabled = true;
    try { await postAlert(`/api/agent/alerts/${read.dataset.alertRead}/read`); await loadAlerts(); $("#alerts-close").focus(); }
    catch (err) { read.disabled = false; $("#alerts-status").textContent = "No se pudo marcar el aviso. Reintenta."; }
  });
  $("#alerts-read-all").addEventListener("click", (e) => spinWhile(e.currentTarget, async () => {
    try { await postAlert("/api/agent/alerts/read-all"); await loadAlerts(); }
    catch (err) { $("#alerts-status").textContent = "No se pudieron marcar los avisos. Reintenta."; }
  }));
  document.addEventListener("visibilitychange", () => { if (!document.hidden) loadAlerts(); });
  setInterval(loadAlerts, 60000);
  loadAlertPrefs().then(loadAlerts);
}

initAlerts();
