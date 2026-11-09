"""Regenera artefactos de A2 sin reentrenar modelos ni alterar series prospectivas registradas."""

import json
from unittest.mock import patch

from pro_backtest import main as regenerate_professional

from footy import config
from footy.betting import suggestions as sg
from footy.db.repository import utc_now
from footy.evaluation import live
from footy.leagues import PARAMS_PATH


def main() -> None:
    with patch.object(sg, "MAX_STAKE", 0.025), patch.dict(sg.RULES, {"max_stake": 0.025}):
        previous = live._combo_backtest()["suggestions"]
    regenerated = live._combo_backtest()
    current = regenerated["suggestions"]
    key = f"{PARAMS_PATH.stat().st_mtime_ns}|4|v2"
    live.CACHE_PATH.write_text(json.dumps({**regenerated, "_key": key}, ensure_ascii=False), encoding="utf-8")
    regenerate_professional()
    professional = json.loads((config.path("processed") / "pro/backtest.json").read_text(encoding="utf-8"))
    lines = ["# Revisión A2 — Riesgo unificado en 2%", "", f"Generado {utc_now()}.", "",
             "Regenerado con `scripts/regenerate_stake_reports.py`, sin reentrenar ni seleccionar umbrales nuevos. "
             "La comparación usa los mismos datos y modelos, cambiando solo el tope de la regla original.", "",
             "| Tope | Apuestas | Yield plano | Banca final (inicio 100) | Caída máxima Kelly |",
             "|---|---:|---:|---:|---:|"]
    for cap, result in [(0.025, previous), (0.02, current)]:
        lines.append(f"| {cap:.1%} | {result['n']} | {result['yield']:+.2%} | "
                     f"{result['kelly_final']:.2f} | {result['kelly_max_dd']:.2%} |")
    lines += ["", "El cambio de tope también puede cambiar el orden por crecimiento esperado y la selección por "
              "partido. Se regenera la curva completa en data/processed/combo_backtest.json, no se escalan cifras.", "",
              "El profesional ya usaba 2% por apuesta y 10% diario: se recalcula su informe 06 con los CSV locales. "
              "Los informes 02/03 evalúan otra regla histórica mediante betting.backtest, con su propio tope 5% "
              "y apuestas planas: sus cifras no dependen de suggestions.MAX_STAKE. Se preserva su experimento, "
              "sin presentarlo como la política de producción.", ""]
    (config.PROJECT_ROOT / "docs/analisis/10_riesgo_unificado.md").write_text("\n".join(lines), encoding="utf-8")
    # Actualizar la tabla profesional citada en README desde el mismo artefacto recién generado.
    readme = config.PROJECT_ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    start = text.index("| Selección 2013-2021 |")
    end = text.index("\n\n", start)
    rows = []
    def pct(value: float) -> str:
        return f"{value:+.1%}".replace(".", ",").replace("%", " %").replace("-", "−")

    for name, group in [("Selección", professional["selection"]), ("Prueba", professional["test"])]:
        bank = f"{group['kelly_bank']:.1f}".replace(".", ",")
        rows.append(f"| {name} {group['period']} | {group['n']} | {pct(group['clv'])} | "
                    f"{group['clv_pos']:.0%} | {pct(group['yield'])} "
                    f"[{pct(group['ci'][0])}; {pct(group['ci'][1])}] | {bank} |")
    text = text[:start] + "\n".join(rows) + text[end:]
    readme.write_text(text, encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
