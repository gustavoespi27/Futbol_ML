"use strict";
/* Modelo de pasos de presentación, independiente del DOM. */
(function (root) {
  const labels = {
    request_odds: "Consultó al Ojeador", get_recommendations: "Recomendaciones de la máquina",
    find_team: "Buscó el equipo", analyze_match: "Analizó el partido", get_upcoming_matches: "Consultó el calendario",
    get_team_form: "Revisó la forma del equipo", simulate_match: "Simuló el partido",
    get_league_standings: "Consultó la tabla", get_value_bets: "Buscó cuotas con valor",
    get_coverage: "Revisó la cobertura", get_system_performance: "Consultó la fiabilidad",
    get_stake_limits: "Consultó los límites", create_watch: "Creó una vigilancia",
    list_watches: "Consultó las vigilancias", cancel_watch: "Canceló una vigilancia", add_favorite: "Guardó un favorito",
  };
  const kinds = { observation: "Observación", deviation: "Desvío", recovery: "Recuperación",
    repair: "Reparación", policy: "Regla del sistema" };
  function enabled(search, saved) {
    const query = new URLSearchParams(search);
    return query.has("demo") ? !["0", "false"].includes(query.get("demo")) : saved === "1";
  }
  function append(rows, event, data) {
    if (event === "step") return [...rows, { type: "step", label: kinds[data.kind] || "Observación", text: data.text || "" }];
    if (event === "tool_start") return [...rows, { type: "tool", tool: data.tool,
      label: labels[data.tool] || "Consultó el sistema", pending: true }];
    if (event === "tool_result") {
      const result = { type: "tool", tool: data.tool, label: labels[data.tool] || "Consultó el sistema",
        pending: false, success: data.success === true, text: data.summary || "",
        ms: Number.isFinite(data.elapsed_ms) && data.elapsed_ms >= 0 ? data.elapsed_ms : null };
      const index = rows.findLastIndex(row => row.type === "tool" && row.tool === data.tool && row.pending);
      return index < 0 ? [...rows, result] : rows.map((row, i) => i === index ? result : row);
    }
    return rows;
  }
  const api = { enabled, append, labels };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.FootyDemo = api;
})(typeof window !== "undefined" ? window : globalThis);
