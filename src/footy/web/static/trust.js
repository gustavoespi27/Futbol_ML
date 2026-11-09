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

  const rules = { classify, emptyKind, briefingLabel };
  if (typeof module !== "undefined" && module.exports) module.exports = rules;
  else root.FootyTrust = rules;
})(typeof window !== "undefined" ? window : globalThis);
