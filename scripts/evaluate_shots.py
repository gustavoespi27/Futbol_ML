"""Análisis 04: ¿mejora Dixon-Coles si se entrena con tiros además de goles?

Para cada liga con estadísticas (formato "main" de football-data), reutiliza los
hiperparámetros del análisis 03 y elige en VALIDACIÓN la proporción goles/tiros
(mix = 1 es el modelo original). Compara en TEST, partido a partido, contra el
análisis 03 (mismos partidos, mismo Elo).

Uso:  python scripts/evaluate_shots.py [--workers 10] [CODES...]
"""

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import screen_leagues as sl  # noqa: E402

from footy import config  # noqa: E402
from footy.ingest.football_data import leagues  # noqa: E402

MIX_GRID = [1.0, 0.75, 0.5, 0.25]
SHOTS = config.path("processed") / "shots"
OUT_DIR = config.PROJECT_ROOT / "docs" / "analisis"
MODELS = ("Dixon-Coles", "Elo+DC", "Elo+DC+Mercado", "Mercado")


def per_match_ll(path: Path) -> pd.DataFrame:
    """Log loss por partido de cada modelo, solo test con Pinnacle."""
    f = pd.read_csv(path)
    f = f[(f.period == "test") & f[["pin_H", "pin_D", "pin_A"]].notna().all(axis=1)]
    out = pd.DataFrame({"match_id": f.match_id.to_numpy()})
    y = f.y.to_numpy()
    for m in MODELS:
        P = f[[f"{m}_pH", f"{m}_pD", f"{m}_pA"]].to_numpy()
        out[m] = -np.log(np.clip(P[np.arange(len(y)), y], 1e-15, 1))
    return out


def paired_ci(diff: np.ndarray, n_boot: int = 5000, seed: int = 0) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    means = rng.choice(diff, size=(n_boot, len(diff)), replace=True).mean(axis=1)
    return float(diff.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def report(codes: list[str]) -> None:
    rows, pooled = [], []
    for code in codes:
        new_json = SHOTS / f"{code}.json"
        if not new_json.exists():
            continue
        new, old = json.loads(new_json.read_text()), json.loads((sl.CACHE / f"{code}.json").read_text())
        a = per_match_ll(sl.CACHE / f"wf_{code}.csv").set_index("match_id")
        b = per_match_ll(SHOTS / f"wf_{code}.csv").set_index("match_id").loc[a.index]
        d_dc = (b["Dixon-Coles"] - a["Dixon-Coles"]).to_numpy()
        d_ens = (b["Elo+DC"] - a["Elo+DC"]).to_numpy()
        d_blend = (b["Elo+DC+Mercado"] - a["Elo+DC+Mercado"]).to_numpy()
        pooled.append(pd.DataFrame({"dc": d_dc, "ens": d_ens, "blend": d_blend}))
        mean, lo, hi = paired_ci(d_dc)
        rows.append({
            "Liga": f"{code} · {new['name']}", "mix elegido": new["dc_params"]["mix"],
            "Partidos test": len(d_dc),
            "Δ DC (tiros − goles)": f"{mean * 1000:+.1f} [{lo * 1000:+.1f}, {hi * 1000:+.1f}]",
            "Δ Elo+DC vs mercado antes": f"{old['d_model_test'] * 1000:+.1f}",
            "Δ Elo+DC vs mercado ahora": f"{new['d_model_test'] * 1000:+.1f}",
            "Δ ensamble vs mercado antes": f"{old['d_blend_test'] * 1000:+.1f}",
            "Δ ensamble vs mercado ahora": f"{new['d_blend_test'] * 1000:+.1f}",
            "Yield test antes": _pct(old.get("test_yield_blend_pin")),
            "Yield test ahora": _pct(new.get("test_yield_blend_pin")),
            "Apuestas ahora": new.get("test_bets_blend_pin"),
            "_old": old["d_model_test"], "_new": new["d_model_test"], "_code": code,
        })
    t = pd.DataFrame(rows)
    p = pd.concat(pooled)
    tot = {k: paired_ci(p[k].to_numpy()) for k in ("dc", "ens", "blend")}
    fig_compare(t)
    n_better = int((t._new < t._old).sum())
    n_beat_market = int((t._new < 0).sum())
    fmt = lambda k: f"{tot[k][0] * 1000:+.2f} (IC95% [{tot[k][1] * 1000:+.2f}, {tot[k][2] * 1000:+.2f}])"  # noqa: E731
    md = f"""# Análisis 04 — Dixon-Coles con tiros

*Generado por `scripts/evaluate_shots.py`.*

El objetivo del modelo pasa de "goles" a `mix × goles + (1 − mix) × goles esperados por tiros`,
con los coeficientes de tiros al arco / fuera estimados en cada ventana de entrenamiento (sin leakage).
`mix` se elige en validación 2016-21 entre {MIX_GRID}; el resto de hiperparámetros es el del análisis 03.
Comparación en test 2022-25, **partido a partido** (Δ log loss × 1000; negativo = mejora).

**Resultado agregado ({len(p)} partidos de test, {len(t)} ligas):**

- Dixon-Coles con tiros vs solo goles: **{fmt("dc")}**
- Elo+DC con tiros vs sin tiros: **{fmt("ens")}**
- Ensamble con el mercado, con tiros vs sin tiros: **{fmt("blend")}**
- El modelo Elo+DC mejora en **{n_better} de {len(t)}** ligas; supera al mercado en **{n_beat_market} de {len(t)}**.

![Comparación](figs/04_tiros.png)

{t.drop(columns=["_old", "_new", "_code"]).to_markdown(index=False)}
"""
    (OUT_DIR / "04_tiros.md").write_text(md, encoding="utf-8")
    print(f"Informe: {OUT_DIR / '04_tiros.md'}")
    print(md.split("![")[0])


def _pct(v):
    return "" if v is None else f"{v:+.1%}"


def fig_compare(t: pd.DataFrame) -> None:
    t = t.sort_values("_new")
    fig, ax = plt.subplots(figsize=(8, 0.3 * len(t) + 1.3), facecolor=sl.SURFACE)
    y = np.arange(len(t))
    ax.axvline(0, color=sl.INK_2, linewidth=1)
    for yi, o, n in zip(y, t._old * 1000, t._new * 1000):
        ax.plot([o, n], [yi, yi], color=sl.GRID_C, linewidth=2, zorder=1)
    ax.scatter(t._old * 1000, y, s=28, color=sl.C2, label="Solo goles (análisis 03)", zorder=3,
               edgecolors=sl.SURFACE, linewidths=1)
    ax.scatter(t._new * 1000, y, s=36, color=sl.C1, label="Con tiros", zorder=4, edgecolors=sl.SURFACE, linewidths=1)
    ax.set_yticks(y, t.Liga, fontsize=7)
    ax.set_facecolor(sl.SURFACE)
    ax.set_title("Elo+DC: log loss menos el del mercado en test (×1000). Izquierda de 0 = mejor que el mercado",
                 loc="left", color=sl.INK, fontsize=9)
    ax.set_xlabel("Δ log loss × 1000", color=sl.INK_2, fontsize=8)
    ax.tick_params(colors=sl.INK_2, labelsize=7, length=0)
    ax.grid(axis="x", color=sl.GRID_C, linewidth=0.6)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.legend(frameon=False, fontsize=8, labelcolor=sl.INK_2, loc="lower right")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "figs" / "04_tiros.png", dpi=150, facecolor=sl.SURFACE)
    plt.close(fig)


def _run(code):
    return sl.run_league(code, MIX_GRID, SHOTS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*")
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)
    codes = args.codes or list(leagues()["main"])
    todo = [c for c in codes if not (SHOTS / f"{c}.json").exists()]
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_run, c): c for c in todo}
        for fut in as_completed(futures):
            code = futures[fut]
            try:
                r = fut.result()
                print(f"{code}: mix {r['dc_params']['mix']}, Δ modelo test {r['d_model_test']:+.4f}", flush=True)
            except Exception as e:
                print(f"{code}: ERROR {e!r}", flush=True)
    report(codes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
