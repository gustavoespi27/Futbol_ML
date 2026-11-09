"use strict";
/* Reglas de presentación P0, independientes del DOM y del motor estadístico. */
(function (root) {
  function classify(overview, now = Date.now()) {
    const stamp = overview && overview.last_daily_run;
    const time = stamp ? Date.parse(stamp) : NaN;
    if (!Number.isFinite(time) || time > now + 300000) return "unknown";
    return now - time >= 30 * 3600000 ? "stale" : "fresh";
  }

  function emptyKind(state, matches, opportunities, references = matches) {
    if (state !== "fresh") return state;
    if (matches === 0) return "no_matches";
    if (references === 0) return "no_reference";
    return opportunities === 0 ? "no_value" : null;
  }

  function briefingLabel(done) {
    if (done.iterations === 0) return "Resumen automático (sin IA)";
    if (!done.success) return "No se completó la redacción del asistente.";
    return "Redactado por el asistente con datos del sistema";
  }

  const partidos = (n) => `${n} partido${n === 1 ? "" : "s"}`;

  function coverage(list) {
    const reference = list.filter(m => m.pro && m.pro.length).length;
    return { reference, total: list.length, missing: list.length - reference,
      label: `${reference} de ${list.length} con Pinnacle` };
  }

  function updatedTime(iso, now = Date.now()) {
    const options = { timeZone: "America/Santiago" };
    const calendarDay = date => {
      const p = Object.fromEntries(new Intl.DateTimeFormat("en", { ...options, year: "numeric", month: "2-digit", day: "2-digit" })
        .formatToParts(date).map(x => [x.type, x.value]));
      return Date.UTC(+p.year, +p.month - 1, +p.day);
    };
    const date = new Date(iso), days = (calendarDay(new Date(now)) - calendarDay(date)) / 86400000;
    const time = new Intl.DateTimeFormat("es-CL", { ...options, hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
    return days === 0 ? `hoy a las ${time}` : days === 1 ? `ayer a las ${time}`
      : `el ${new Intl.DateTimeFormat("es-CL", { ...options, day: "numeric", month: "long", year: "numeric" }).format(date)}`;
  }

  const rules = { classify, emptyKind, briefingLabel, partidos, coverage, updatedTime };
  if (typeof module !== "undefined" && module.exports) module.exports = rules;
  else root.FootyTrust = rules;
})(typeof window !== "undefined" ? window : globalThis);
