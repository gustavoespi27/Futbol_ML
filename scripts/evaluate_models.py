"""Análisis 02: Elo y Dixon-Coles vs mercado con walk-forward (ARG, BRA).

Uso:  python scripts/evaluate_models.py [ARG BRA]
Salida: docs/analisis/02_modelos.md, figuras, config/model_params.json
        y predicciones en data/processed/wf_<liga>.csv
"""

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from footy import config
from footy.data import load_matches
from footy.db.connection import connect
from footy.evaluation import metrics
from footy.evaluation.pipeline import EV_GRID, PERIODS, evaluate, tune

# Competiciones usadas para ENTRENAR cada liga (la copa argentina aporta partidos entre los mismos equipos)
FAMILIES = {"ARG": ["ARG", "ARGC"], "BRA": ["BRA"]}

OUT = config.PROJECT_ROOT / "docs" / "analisis"
FIG = OUT / "figs"
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"


def style(ax, title, xlabel, ylabel):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=10)
    ax.set_xlabel(xlabel, color=INK_2, fontsize=9)
    ax.set_ylabel(ylabel, color=INK_2, fontsize=9)
    ax.tick_params(colors=INK_2, labelsize=8, length=0)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)


def fig_curves(results):
    fig, axes = plt.subplots(len(results), 2, figsize=(11, 3.2 * len(results)), facecolor=SURFACE, squeeze=False)
    for row, res in zip(axes, results):
        for ax, strat in zip(row, ("Elo+DC", "Elo+DC+Mercado")):
            ax.axhline(0, color=INK_2, linewidth=1)
            for label, color in (("Pinnacle", C1), ("Promedio", C2)):
                curve = res.curves.get((strat, "test", label))
                if curve is None or len(curve) < 2:
                    continue
                ax.plot(np.arange(len(curve)), curve, color=color, linewidth=2, label=label)
                ax.annotate(f"{curve[-1]:+.1f} u", (len(curve) - 1, curve[-1]), xytext=(4, 0),
                            textcoords="offset points", color=INK_2, fontsize=8, va="center")
            style(ax, f"{res.code} · {strat} · EV > {res.chosen[strat]:.0%} (test 2022-25)",
                  "Apuestas (orden cronológico)", "Beneficio acumulado (unidades)")
        row[0].legend(frameon=False, fontsize=8, labelcolor=INK_2)
    fig.tight_layout()
    fig.savefig(FIG / "02_beneficio_test.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


def fig_calibration(results):
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6), facecolor=SURFACE)
    for ax, (k, lab) in zip(axes, enumerate(("Local", "Empate", "Visita"))):
        ax.plot([0, 1], [0, 1], color=INK_2, linewidth=1, linestyle="--")
        for res, color in zip(results, (C1, C2)):
            t = res.frame[res.frame.period == "test"]
            p = t[f"Elo+DC_p{'HDA'[k]}"].to_numpy()
            tab = metrics.calibration_table(p, (t.y == k).to_numpy(), bins=np.arange(0, 1.0001, 0.1))
            tab = tab[tab.n >= 30]
            ax.plot(tab.pred, tab.obs, color=color, linewidth=2, marker="o", markersize=5,
                    markeredgecolor=SURFACE, label=res.code)
        hi = 0.8 if k != 1 else 0.45
        ax.set_xlim(0, hi), ax.set_ylim(0, hi)
        style(ax, lab, "Probabilidad Elo+DC", "Frecuencia observada")
    axes[0].legend(frameon=False, fontsize=8, labelcolor=INK_2)
    fig.suptitle("Calibración del modelo Elo+DC en test (2022-25)", x=0.01, ha="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG / "02_calibracion_modelo.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


def pct(x):
    return f"{x:+.1%}" if pd.notna(x) else ""


def league_section(res) -> str:
    met = res.metrics.copy()
    pin = met[met.modelo == "Mercado"].set_index("periodo").log_loss
    met["Δ log loss vs mercado"] = met.apply(lambda r: r.log_loss - pin[r.periodo], axis=1)
    for c in ("log_loss", "rps", "brier", "Δ log loss vs mercado"):
        met[c] = met[c].map(lambda v: f"{v:.4f}")
    met["accuracy"] = met.accuracy.map(lambda v: f"{v:.1%}")

    b = res.betting.copy()
    chosen = b[(b.periodo != "val") & (b.elegido_en_val == True)].copy()  # noqa: E712
    for c in ("acierto", "yield"):
        chosen[c] = chosen[c].map(lambda v: f"{v:.1%}" if c == "acierto" else pct(v))
    chosen["cuota_media"] = chosen.cuota_media.map(lambda v: f"{v:.2f}")
    chosen["kelly_profit_%"] = chosen["kelly_profit_%"].map(lambda v: f"{v:+.1f}%")
    chosen["kelly_max_dd"] = chosen.kelly_max_dd.map(lambda v: f"{v:.1%}")
    chosen["max_dd_u"] = chosen.max_dd_u.map(lambda v: f"{v:.1f}")
    cols = ["estrategia", "periodo", "cuota", "min_ev", "apuestas", "acierto", "cuota_media", "yield",
            "yield_ic95", "max_dd_u", "racha_perd", "kelly_profit_%", "kelly_max_dd", "mix"]
    chosen = chosen.reindex(columns=cols).fillna("")

    all_test = b[(b.periodo == "test") & (b.cuota == "Pinnacle")][["estrategia", "min_ev", "apuestas", "yield", "yield_ic95"]].copy()
    all_test["yield"] = all_test["yield"].map(pct)

    return f"""## {res.code}

**Hiperparámetros elegidos en validación:** Dixon-Coles `{res.dc_params}` · Elo `{res.elo_params}`
**Pesos del ensamble** (log-lineal, ajustados en validación): Elo+DC = {np.round(res.weights_models, 2).tolist()} ·
Elo+DC+Mercado = {np.round(res.weights_market, 2).tolist()} (último peso = mercado)

### Calidad probabilística (mismos partidos; val/test con Pinnacle, live contra el promedio)

{met.to_markdown(index=False)}

### Apuestas con el umbral elegido en validación

Flat = 1 unidad por apuesta. Kelly = ¼ Kelly con tope 5% del bankroll, banca inicial 100.

{chosen.to_markdown(index=False)}

<details><summary>Todos los umbrales en test a cuota Pinnacle (solo transparencia: NO elegir mirando esto)</summary>

{all_test.to_markdown(index=False)}

</details>
"""


def main(codes):
    FIG.mkdir(parents=True, exist_ok=True)
    conn = connect()
    results, params = [], {}
    for code in codes:
        df = load_matches(conn, FAMILIES[code])
        dc_p, elo_p = tune(df, code)
        res = evaluate(df, code, dc_p, elo_p)
        results.append(res)
        params[code] = {"dixon_coles": dc_p, "elo": elo_p,
                        "weights_elo_dc": res.weights_models.tolist(),
                        "weights_elo_dc_market": res.weights_market.tolist(),
                        "min_ev": res.chosen, "train_competitions": FAMILIES[code]}
        res.frame.drop(columns=["kickoff"]).to_csv(config.path("processed") / f"wf_{code}.csv", index=False)
        print(res.metrics.to_string())
    fig_curves(results)
    fig_calibration(results)
    (config.PROJECT_ROOT / "config" / "model_params.json").write_text(json.dumps(params, indent=2), encoding="utf-8")

    md = f"""# Análisis 02 — Elo y Dixon-Coles contra el mercado (walk-forward)

*Generado por `scripts/evaluate_models.py`.*

**Diseño (sin leakage):** predicción semanal; cada semana el modelo se ajusta solo con partidos anteriores.
Validación {PERIODS['val'][0][:4]}-{int(PERIODS['val'][1][:4]) - 1}: se eligen hiperparámetros, pesos y umbral de EV.
Test {PERIODS['test'][0][:4]}-{int(PERIODS['test'][1][:4]) - 1}: evaluación única. Live 2026: sin Pinnacle.
Umbrales probados: {EV_GRID}. El umbral se elige por yield en validación con al menos 100 apuestas.

**Mercado** = cuotas de cierre de Pinnacle sin margen (proporcional). Apostar a cuota de cierre es el
escenario más exigente: el precio ya incorpora toda la información previa al partido.
"Máxima" es la mejor cuota entre casas: cota superior **no alcanzable** en la práctica.

{"".join(league_section(r) for r in results)}

![Beneficio acumulado en test](figs/02_beneficio_test.png)

![Calibración del modelo](figs/02_calibracion_modelo.png)
"""
    (OUT / "02_modelos.md").write_text(md, encoding="utf-8")
    print(f"Informe: {OUT / '02_modelos.md'}")


if __name__ == "__main__":
    main(sys.argv[1:] or list(FAMILIES))
