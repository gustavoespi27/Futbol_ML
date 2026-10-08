"""Análisis 03: ¿en qué liga (si en alguna) el modelo supera al mercado?

Aplica a cada liga de config/football_data.yaml el mismo pipeline walk-forward
(ajuste en validación 2016-21, test 2022-25) y el criterio pre-registrado en
docs/decisiones.md. Reanudable: cada liga se guarda en data/processed/screen/<code>.json.

Uso:  python scripts/screen_leagues.py [--workers 8] [CODES...]
"""

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from footy import config
from footy.betting.devig import overround
from footy.data import has_odds, load_matches, odds_matrix
from footy.db.connection import connect
from footy.evaluation.metrics import bootstrap_mean_ci
from footy.evaluation.pipeline import evaluate, tune
from footy.ingest.football_data import leagues

# Grillas reducidas (37 ligas); los bordes elegidos se reportan para detectar grillas cortas.
DC_GRID = {"xi": [0.001, 0.002, 0.004], "alpha": [3e-3, 1e-2, 3e-2]}
ELO_GRID = {"k": [10, 20, 30], "home_adv": [30, 70, 110], "new_team_offset": [50, 150], "season_regress": [0.1, 0.3]}
N_TESTS = len(leagues()["extra"]) + len(leagues()["main"])
BONFERRONI_ALPHA = 0.05 / N_TESTS

OUT_DIR = config.PROJECT_ROOT / "docs" / "analisis"
CACHE = config.path("processed") / "screen"
SURFACE, INK, INK_2, GRID_C = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
C1, C2 = "#2a78d6", "#eb6834"


def family(code: str) -> tuple[list[str], list[str]]:
    """(competiciones para Elo, competiciones para Dixon-Coles)."""
    cfg = leagues()
    if code == "ARG":
        return ["ARG", "ARGC"], ["ARG", "ARGC"]
    if code in cfg["main"]:
        country = cfg["main"][code]["country"]
        return [c for c, v in cfg["main"].items() if v["country"] == country], [code]
    return [code], [code]


def run_league(code: str) -> dict:
    elo_comps, dc_comps = family(code)
    df = load_matches(connect(), elo_comps)
    dc_p, elo_p = tune(df, code, DC_GRID, ELO_GRID, dc_comps)
    res = evaluate(df, code, dc_p, elo_p, dc_comps)
    f = res.frame
    res.frame.drop(columns=["kickoff"]).to_csv(CACHE / f"wf_{code}.csv", index=False)

    met = res.metrics.set_index(["periodo", "modelo"]).log_loss
    out = {"code": code, "name": (leagues()["extra"].get(code) or leagues()["main"][code])["name"],
           "dc_params": dc_p, "elo_params": elo_p,
           "w_blend": res.weights_market.tolist(), "min_ev": res.chosen}
    for period in ("val", "test"):
        m = (f.period == period).to_numpy() & has_odds(f, "pin")
        out[f"n_{period}"] = int(m.sum())
        out[f"margin_pin_{period}"] = float(overround(odds_matrix(f[m], "pin")).mean()) if m.any() else None
        ma = (f.period == period).to_numpy() & has_odds(f, "avg")
        out[f"margin_avg_{period}"] = float(overround(odds_matrix(f[ma], "avg")).mean()) if ma.any() else None
        if (period, "Mercado") not in met:
            continue
        out[f"ll_market_{period}"] = float(met[(period, "Mercado")])
        out[f"d_model_{period}"] = float(met[(period, "Elo+DC")] - met[(period, "Mercado")])
        out[f"d_blend_{period}"] = float(met[(period, "Elo+DC+Mercado")] - met[(period, "Mercado")])

    b = res.betting
    for strat, key in (("Elo+DC", "model"), ("Elo+DC+Mercado", "blend")):
        thr = res.chosen[strat]
        val = b[(b.estrategia == strat) & (b.periodo == "val") & (b.min_ev == thr)]
        out[f"val_yield_{key}"] = float(val["yield"].iloc[0]) if len(val) else None
        out[f"val_bets_{key}"] = int(val["apuestas"].iloc[0]) if len(val) else 0
        for book, label in (("pin", "Pinnacle"), ("avg", "Promedio")):
            t = b[(b.estrategia == strat) & (b.periodo == "test") & (b.cuota == label) & (b.min_ev == thr)]
            out[f"test_yield_{key}_{book}"] = float(t["yield"].iloc[0]) if len(t) else None
            out[f"test_bets_{key}_{book}"] = int(t["apuestas"].iloc[0]) if len(t) else 0
            out[f"test_ci_{key}_{book}"] = t["yield_ic95"].iloc[0] if len(t) else ""
    out["test_ci_bonf_blend_pin"] = _bonferroni_ci(f, res, "Elo+DC+Mercado")
    (CACHE / f"{code}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def _bonferroni_ci(f, res, strat) -> str:
    from footy.betting.backtest import select_bets
    m = (f.period == "test").to_numpy() & has_odds(f, "pin")
    P = f[[f"{strat}_pH", f"{strat}_pD", f"{strat}_pA"]].to_numpy()[m]
    bets = select_bets(P, odds_matrix(f[m], "pin"), res.chosen[strat])
    if len(bets) < 10:
        return ""
    won = f.y.to_numpy()[m][bets.idx] == bets.sel.to_numpy()
    lo, hi = bootstrap_mean_ci(np.where(won, bets.odds - 1, -1.0), alpha=BONFERRONI_ALPHA, n_boot=5000)
    return f"[{lo:+.1%}, {hi:+.1%}]"


def classify(r: dict) -> str:
    """Criterio pre-registrado (docs/decisiones.md, 2026-10-08)."""
    cand = (r.get("d_blend_val") is not None and r["d_blend_val"] < -0.001
            and (r.get("val_yield_blend") or -1) > 0)
    if not cand:
        return "no"
    conf = (r.get("d_blend_test") is not None and r["d_blend_test"] < 0
            and (r.get("test_yield_blend_pin") or -1) > 0)
    return "CONFIRMADA" if conf else "candidata (falla en test)"


def fig_delta(df: pd.DataFrame) -> None:
    d = df.sort_values("d_model_test")
    fig, ax = plt.subplots(figsize=(8, 0.28 * len(d) + 1.2), facecolor=SURFACE)
    y = np.arange(len(d))
    ax.axvline(0, color=INK_2, linewidth=1)
    ax.scatter(d.d_model_val * 1000, y, s=28, color=C2, label="Validación 2016-21", zorder=3,
               edgecolors=SURFACE, linewidths=1)
    ax.scatter(d.d_model_test * 1000, y, s=36, color=C1, label="Test 2022-25", zorder=4,
               edgecolors=SURFACE, linewidths=1)
    ax.set_yticks(y, [f"{c} · {n}" for c, n in zip(d.code, d.name)], fontsize=7)
    ax.set_facecolor(SURFACE)
    ax.set_title("Log loss del modelo Elo+DC menos el del mercado (×1000). A la izquierda de 0 = mejor que el mercado",
                 loc="left", color=INK, fontsize=9)
    ax.set_xlabel("Δ log loss × 1000", color=INK_2, fontsize=8)
    ax.tick_params(colors=INK_2, labelsize=7, length=0)
    ax.grid(axis="x", color=GRID_C, linewidth=0.6)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK_2, loc="lower right")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "figs" / "03_delta_ligas.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


def report(rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    df["criterio"] = [classify(r) for r in rows]
    fig_delta(df)
    pct = lambda v: "" if v is None or pd.isna(v) else f"{v:+.1%}"  # noqa: E731
    pct0 = lambda v: "" if v is None or pd.isna(v) else f"{v:.1%}"  # noqa: E731
    ll = lambda v: "" if v is None or pd.isna(v) else f"{v * 1000:+.1f}"  # noqa: E731

    t1 = pd.DataFrame({
        "Liga": df.code + " · " + df.name,
        "Partidos test": df.n_test,
        "Margen Pinnacle": df.margin_pin_test.map(pct0),
        "Margen promedio": df.margin_avg_test.map(pct0),
        "LL mercado test": df.ll_market_test.map(lambda v: f"{v:.4f}"),
        "Δ modelo val": df.d_model_val.map(ll), "Δ modelo test": df.d_model_test.map(ll),
        "Δ ensamble val": df.d_blend_val.map(ll), "Δ ensamble test": df.d_blend_test.map(ll),
    }).sort_values("LL mercado test")

    t2 = pd.DataFrame({
        "Liga": df.code, "Umbral EV": df.min_ev.map(lambda d: f"{d['Elo+DC+Mercado']:.0%}"),
        "Yield val": df.val_yield_blend.map(pct), "Apuestas val": df.val_bets_blend,
        "Yield test Pinnacle": df.test_yield_blend_pin.map(pct), "Apuestas test": df.test_bets_blend_pin,
        "IC95%": df.test_ci_blend_pin, f"IC Bonferroni": df.test_ci_bonf_blend_pin,
        "Yield test promedio": df.test_yield_blend_avg.map(pct),
        "Yield test modelo solo (Pinnacle)": df.test_yield_model_pin.map(pct),
        "Criterio": df.criterio,
    })

    n_better_test = int((df.d_model_test < 0).sum())
    n_blend_better = int((df.d_blend_test < 0).sum())
    md = f"""# Análisis 03 — Comparación de {len(df)} ligas: ¿dónde supera el modelo al mercado?

*Generado por `scripts/screen_leagues.py`. Criterio pre-registrado en [decisiones.md](../decisiones.md).*

Mismo pipeline que el análisis 02 con grillas reducidas: Elo entrenado con todas las divisiones del país
(los ascendidos llegan con historial), Dixon-Coles con la liga evaluada. Validación 2016-21, test 2022-25,
mercado = cierre de Pinnacle sin margen.

**Resumen:** el modelo solo (Elo+DC) supera al mercado en test en **{n_better_test} de {len(df)}** ligas.
El ensamble con el mercado mejora al mercado en test en **{n_blend_better} de {len(df)}**.
Ligas que cumplen el criterio pre-registrado: **{", ".join(df.code[df.criterio == "CONFIRMADA"]) or "ninguna"}**.

![Δ log loss por liga](figs/03_delta_ligas.png)

## Calidad probabilística (Δ = log loss − log loss del mercado, × 1000; negativo = mejor que el mercado)

Ordenado de la liga más predecible a la menos predecible para el mercado.

{t1.to_markdown(index=False)}

## Apuestas con el ensamble Elo+DC+Mercado (umbral elegido en validación)

"IC Bonferroni" corrige por las {N_TESTS} ligas comparadas (nivel {1 - BONFERRONI_ALPHA:.2%}).

{t2.to_markdown(index=False)}
"""
    (OUT_DIR / "03_ligas.md").write_text(md, encoding="utf-8")
    df.to_csv(CACHE / "summary.csv", index=False)
    print(f"Informe: {OUT_DIR / '03_ligas.md'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    cfg = leagues()
    codes = args.codes or [*cfg["extra"], *cfg["main"]]
    todo = [c for c in codes if not (CACHE / f"{c}.json").exists()]
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(run_league, c): c for c in todo}
        for fut in as_completed(futures):
            code = futures[fut]
            try:
                r = fut.result()
                print(f"{code}: Δ modelo test {r.get('d_model_test')}, Δ ensamble test {r.get('d_blend_test')}", flush=True)
            except Exception as e:  # una liga con datos raros no detiene el resto
                print(f"{code}: ERROR {e!r}", flush=True)
    rows = [json.loads((CACHE / f"{c}.json").read_text(encoding="utf-8"))
            for c in codes if (CACHE / f"{c}.json").exists()]
    report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
