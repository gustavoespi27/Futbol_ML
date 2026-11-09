"use strict";
/* Presentación de montos CLP; los cálculos siguen recibiendo números. */
(function (root) {
  const currency = new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 });
  const decimal = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 20 });
  const money = value => value == null || !Number.isFinite(Number(value)) ? "–" : currency.format(Number(value));
  const amount = value => decimal.format(Number(value));
  function parseAmount(value) {
    if (typeof value === "number") return Number.isFinite(value) ? value : NaN;
    let text = String(value).trim().replace(/[$\s]/g, "");
    if (!text) return NaN;
    if (/^-?\d{1,3}(\.\d{3})+(,\d+)?$/.test(text)) text = text.replace(/\./g, "");
    if (!/^-?\d+(?:[.,]\d+)?$/.test(text)) return NaN;
    const parsed = Number(text.replace(",", "."));
    return Number.isFinite(parsed) ? parsed : NaN;
  }
  const rules = { money, amount, parseAmount };
  if (typeof module !== "undefined" && module.exports) module.exports = rules;
  else root.FootyFormat = rules;
})(typeof window !== "undefined" ? window : globalThis);
