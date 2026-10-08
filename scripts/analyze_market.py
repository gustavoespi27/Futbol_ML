"""Análisis 01: ¿qué tan bueno es el mercado de cierre 1X2 en Argentina y Brasil?

Responde, antes de construir ningún modelo:
1. Cuánto margen cobran las casas (el umbral mínimo de ventaja necesario).
2. Qué log loss / RPS logra el mercado sin margen (la vara que el modelo debe superar).
3. Si las probabilidades del mercado están calibradas.
4. Si existe sesgo favorito-longshot y cuánto rendiría apostar ciegamente por tramo de cuota.

Exploratorio: usa todo el histórico, así que NO sirve para elegir estrategias
(eso exige validación temporal fuera de muestra).

Uso:  python scripts/analyze_market.py   -> docs/analisis/01_mercado_cierre.md + figuras
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from footy import config
from footy.betting import devig
from footy.db.connection import connect
from footy.evaluation import metrics

OUT_DIR = config.PROJECT_ROOT / "docs" / "analisis"
FIG_DIR = OUT_DIR / "figs"
COMPS = ("ARG", "BRA")
SEL = ("H", "D", "A")

# Paleta de referencia (skill dataviz, modo claro): slots 1-3 validados en todos los pares.
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = {"H": "#2a78d6", "D": "#eb6834", "A": "#1baf7a"}
COMP_COLOR = {"ARG": "#2a78d6", "BRA": "#eb6834"}
SEL_LABEL = {"H": "Local", "D": "Empate", "A": "Visita"}


def load(conn) -> pd.DataFrame:
    """Una fila por partido terminado, columnas <bookmaker>_<H|D|A> con cuotas de cierre."""
    df = pd.read_sql_query(
        """SELECT m.id AS match_id, c.code AS comp, m.season, m.kickoff_utc,
                  m.home_goals, m.away_goals, o.bookmaker, o.selection, o.price
           FROM matches m
           JOIN competitions c ON c.id = m.competition_id
           JOIN odds o ON o.match_id = m.id AND o.market = '1X2' AND o.is_closing = 1
           WHERE m.status = 'finished' AND c.code IN ('ARG', 'BRA')""",
        conn,
    )
    wide = df.pivot_table(index=["match_id", "comp", "season", "kickoff_utc", "home_goals", "away_goals"],
                          columns=["bookmaker", "selection"], values="price")
    wide.columns = [f"{b}_{s}" for b, s in wide.columns]
    wide = wide.reset_index().sort_values("kickoff_utc").reset_index(drop=True)
    wide["y"] = np.select([wide.home_goals > wide.away_goals, wide.home_goals == wide.away_goals], [0, 1], 2)
    wide["year"] = wide.kickoff_utc.str[:4].astype(int)
    return wide


def odds_of(df: pd.DataFrame, book: str) -> np.ndarray:
    return df[[f"{book}_{s}" for s in SEL]].to_numpy()


def has(df: pd.DataFrame, book: str) -> pd.Series:
    return df[[f"{book}_{s}" for s in SEL]].notna().all(axis=1)


def naive_probs(df: pd.DataFrame) -> np.ndarray:
    """Frecuencias H/D/A de la competición con partidos ANTERIORES a cada fecha (sin leakage).

    Se excluyen partidos del mismo día para no usar resultados simultáneos.
    """
    out = np.full((len(df), 3), np.nan)
    for comp, g in df.groupby("comp"):
        day = g.kickoff_utc.str[:10]
        counts = pd.get_dummies(g.y).reindex(columns=[0, 1, 2], fill_value=0).astype(float)
        daily = counts.groupby(day).sum()
        prior = daily.cumsum().shift(1).fillna(0) + 1.0   # +1: suavizado de Laplace
        out[g.index] = prior.loc[day].to_numpy() / prior.loc[day].to_numpy().sum(axis=1, keepdims=True)
    return out


def style(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=11)
    ax.set_xlabel(xlabel, color=INK_2, fontsize=9)
    ax.set_ylabel(ylabel, color=INK_2, fontsize=9)
    ax.tick_params(colors=INK_2, labelsize=8, length=0)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)


# --- Secciones ------------------------------------------------------------

def coverage(df):
    books = ["Pinnacle", "Market Avg", "Market Max", "Bet365", "Betfair Exchange"]
    rows = []
    for comp, g in df.groupby("comp"):
        row = {"Liga": comp, "Partidos": len(g), "Desde": g.kickoff_utc.min()[:10], "Hasta": g.kickoff_utc.max()[:10]}
        row.update({b: f"{has(g, b).mean():.0%}" for b in books})
        rows.append(row)
    return pd.DataFrame(rows)


def margins(df):
    books = ["Pinnacle", "Betfair Exchange", "Market Avg", "Bet365"]
    rows = []
    for comp, g in df.groupby("comp"):
        for b in books:
            m = has(g, b)
            if m.sum() < 100:
                continue
            ov = devig.overround(odds_of(g[m], b))
            rows.append({"Liga": comp, "Casa": b, "Partidos": int(m.sum()),
                         "Margen medio": f"{ov.mean():.2%}", "Mediana": f"{np.median(ov):.2%}"})
    by_year = []
    for (comp, year), g in df.groupby(["comp", "year"]):
        rec = {"comp": comp, "year": year}
        for b in ("Pinnacle", "Market Avg"):
            m = has(g, b)
            rec[b] = devig.overround(odds_of(g[m], b)).mean() if m.sum() >= 50 else np.nan
        by_year.append(rec)
    return pd.DataFrame(rows), pd.DataFrame(by_year)


def fig_margins(by_year):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4), sharey=True, facecolor=SURFACE)
    for ax, comp in zip(axes, COMPS):
        g = by_year[by_year.comp == comp]
        for b, color in (("Pinnacle", SERIES["H"]), ("Market Avg", SERIES["D"])):
            ax.plot(g.year, g[b] * 100, color=color, linewidth=2, marker="o", markersize=4, label=b)
            last = g.dropna(subset=[b]).iloc[-1]
            ax.annotate(f"{last[b]:.1%}", (last.year, last[b] * 100), xytext=(4, 0),
                        textcoords="offset points", color=INK_2, fontsize=8, va="center")
        style(ax, f"{comp}: margen medio de cierre 1X2", "Año", "Margen (%)")
        ax.set_ylim(bottom=0)
    axes[0].legend(frameon=False, fontsize=8, labelcolor=INK_2)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "01_margen_por_anio.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


def market_quality(df):
    """Mercado (Pinnacle sin margen, 3 métodos) vs frecuencias históricas, mismos partidos."""
    naive = naive_probs(df)
    rows = []
    for comp, g in df.groupby("comp"):
        m = has(g, "Pinnacle").to_numpy()
        g = g[m]
        y = g.y.to_numpy()
        base = metrics.summary(y, naive[g.index])
        rows.append({"Liga": comp, "Modelo": "Frecuencias históricas (naive)", **base})
        for method in devig.METHODS:
            P = devig.devig(odds_of(g, "Pinnacle"), method)
            rows.append({"Liga": comp, "Modelo": f"Pinnacle cierre ({method})", **metrics.summary(y, P)})
    t = pd.DataFrame(rows)
    return t


def quality_by_year(df):
    rows = []
    for (comp, year), g in df.groupby(["comp", "year"]):
        g = g[has(g, "Pinnacle")]
        if len(g) < 100:
            continue
        P = devig.proportional(odds_of(g, "Pinnacle"))
        y = g.y.to_numpy()
        rows.append({"Liga": comp, "Año": year, "Partidos": len(g),
                     "Log loss": metrics.log_loss(y, P), "RPS": metrics.rps(y, P),
                     "% local": np.mean(y == 0), "% empate": np.mean(y == 1), "% visita": np.mean(y == 2)})
    return pd.DataFrame(rows)


def calibration(df):
    g = df[has(df, "Pinnacle")]
    P = devig.proportional(odds_of(g, "Pinnacle"))
    tables, rows = {}, []
    for k, s in enumerate(SEL):
        outcome = (g.y.to_numpy() == k)
        tables[s] = metrics.calibration_table(P[:, k], outcome, bins=np.arange(0, 1.0001, 0.05))
        for comp in COMPS:
            m = (g.comp == comp).to_numpy()
            rows.append({"Liga": comp, "Resultado": SEL_LABEL[s],
                         "Prob. media mercado": f"{P[m, k].mean():.1%}",
                         "Frecuencia real": f"{outcome[m].mean():.1%}",
                         "ECE": f"{metrics.ece(P[m, k], outcome[m], 10):.2%}"})
    return tables, pd.DataFrame(rows)


def fig_calibration(tables):
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8), facecolor=SURFACE)
    for ax, s in zip(axes, SEL):
        t = tables[s][tables[s].n >= 30]
        ax.plot([0, 1], [0, 1], color=INK_2, linewidth=1, linestyle="--")
        ax.errorbar(t.pred, t.obs, yerr=[t.obs - t.obs_lo, t.obs_hi - t.obs], fmt="o", markersize=5,
                    color=SERIES[s], ecolor=SERIES[s], elinewidth=1.2, capsize=0,
                    markeredgecolor=SURFACE, markeredgewidth=1)
        hi = max(t.pred.max(), t.obs_hi.max()) + 0.05
        ax.set_xlim(0, hi)
        ax.set_ylim(0, hi)
        style(ax, f"{SEL_LABEL[s]}", "Probabilidad del mercado (Pinnacle, sin margen)", "Frecuencia observada")
    fig.suptitle("Calibración del cierre 1X2, ARG + BRA (IC 95%; diagonal = calibración perfecta)",
                 x=0.01, ha="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "02_calibracion.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


def longshot(df):
    """ROI de apostar 1 unidad a TODA selección por tramo de cuota de Pinnacle."""
    g = df[has(df, "Pinnacle")]
    recs = []
    for k, s in enumerate(SEL):
        win = (g.y.to_numpy() == k)
        recs.append(pd.DataFrame({
            "comp": g.comp.to_numpy(), "sel": s, "win": win,
            "pin": g[f"Pinnacle_{s}"].to_numpy(), "avg": g[f"Market Avg_{s}"].to_numpy(),
            "max": g[f"Market Max_{s}"].to_numpy(),
            "p_fair": devig.proportional(odds_of(g, "Pinnacle"))[:, k],
        }))
    bets = pd.concat(recs, ignore_index=True)
    edges = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 10.0, 1000]
    labels = ["1.00-1.50", "1.50-2.00", "2.00-2.50", "2.50-3.00", "3.00-4.00", "4.00-6.00", "6.00-10.0", "10.0+"]
    bets["bucket"] = pd.cut(bets.pin, edges, labels=labels, right=False)

    def roi_rows(frame, key):
        rows = []
        for name, b in frame.groupby(key, observed=True):
            r_pin = np.where(b.win, b.pin - 1, -1.0)
            r_avg = np.where(b.win, b.avg - 1, -1.0)
            mx = b["max"].dropna()
            r_max = np.where(b.win[mx.index], mx - 1, -1.0)
            lo, hi = metrics.bootstrap_mean_ci(r_pin)
            rows.append({key: name, "Apuestas": len(b), "Prob. justa media": b.p_fair.mean(),
                         "Frecuencia real": b.win.mean(),
                         "ROI Pinnacle": r_pin.mean(), "IC95% Pinnacle": f"[{lo:+.1%}, {hi:+.1%}]",
                         "ROI Avg": r_avg.mean(), "ROI Max": r_max.mean()})
        return pd.DataFrame(rows)

    return roi_rows(bets, "bucket"), roi_rows(bets.assign(sel=bets.sel.map(SEL_LABEL)), "sel"), bets


def fig_longshot(bets):
    """Desvío relativo (frecuencia real / prob. justa - 1) con IC 95% de Wilson."""
    fig, ax = plt.subplots(figsize=(8, 3.8), facecolor=SURFACE)
    rows = []
    for name, b in bets.groupby("bucket", observed=True):
        pred, freq, n = b.p_fair.mean(), b.win.mean(), len(b)
        lo, hi = metrics.wilson(freq, n)
        rows.append((str(name), freq / pred - 1, lo / pred - 1, hi / pred - 1, n))
    labels, mid, lo, hi, n = map(np.array, zip(*rows))
    x = np.arange(len(labels))
    ax.axhline(0, color=INK_2, linewidth=1)
    ax.errorbar(x, mid * 100, yerr=[(mid - lo) * 100, (hi - mid) * 100], fmt="o", markersize=6,
                color=SERIES["H"], ecolor=SERIES["H"], elinewidth=1.5, capsize=0,
                markeredgecolor=SURFACE, markeredgewidth=1)
    for xi, v, h, k in zip(x, mid, hi, n):
        ax.annotate(f"{v:+.1%}\nn={k}", (xi, h * 100), xytext=(0, 5), textcoords="offset points",
                    ha="center", color=INK_2, fontsize=7)
    ax.set_xticks(x, labels)
    ax.set_ylim(lo.min() * 100 - 3, hi.max() * 100 + 6)
    style(ax, "Frecuencia real vs probabilidad justa por tramo de cuota (Pinnacle, ARG + BRA, IC 95%)",
          "Tramo de cuota de cierre", "Desvío relativo (%)")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "03_favorito_longshot.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


# --- Reporte --------------------------------------------------------------

def fmt(df: pd.DataFrame, pct=(), dec=()) -> str:
    d = df.copy()
    for c in pct:
        d[c] = d[c].map(lambda v: f"{v:+.1%}" if "ROI" in c else f"{v:.1%}")
    for c in dec:
        d[c] = d[c].map(lambda v: f"{v:.4f}")
    return d.to_markdown(index=False)


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    df = load(connect())

    cov = coverage(df)
    marg, by_year = margins(df)
    fig_margins(by_year)
    qual = market_quality(df)
    qyear = quality_by_year(df)
    cal_tables, cal_summary = calibration(df)
    fig_calibration(cal_tables)
    by_bucket, by_sel, bets = longshot(df)
    fig_longshot(bets)

    naive_ll = qual[qual.Modelo.str.startswith("Frecuencias")].set_index("Liga").log_loss
    pin_ll = qual[qual.Modelo == "Pinnacle cierre (proportional)"].set_index("Liga").log_loss
    skill = (1 - pin_ll / naive_ll)

    md = f"""# Análisis 01 — Mercado de cierre 1X2 en Argentina y Brasil

*Generado por `scripts/analyze_market.py`. Datos: football-data.co.uk (cuotas de cierre).*

> **Exploratorio.** Usa todo el histórico, por lo que ningún patrón de aquí es una estrategia:
> cualquier regla de apuesta debe validarse fuera de muestra con walk-forward.

## 1. Cobertura

{cov.to_markdown(index=False)}

Pinnacle deja de aparecer a fines de 2025 (cierre de su API pública). Desde 2026 la referencia
"sharp" disponible es Betfair Exchange; "Market Avg" existe en todo el período.

## 2. Margen de las casas

{marg.to_markdown(index=False)}

Betfair Exchange no incluye la comisión del exchange (2-5% sobre ganancias netas):
su margen efectivo es mayor que el mostrado.

![Margen por año](figs/01_margen_por_anio.png)

**Implicancia:** para ganar apostando al promedio del mercado, el modelo debe superar un margen
de este orden. Contra Pinnacle el margen es menor, pero Pinnacle es también el precio más eficiente.

## 3. ¿Qué tan bueno es el mercado? (la vara a superar)

Mismos partidos (con cuota Pinnacle). Baseline naive = frecuencias H/D/A de la liga con partidos
anteriores a cada fecha (sin leakage).

{fmt(qual, dec=("log_loss", "rps", "brier", "accuracy"))}

Mejora relativa del mercado sobre el naive en log loss: {", ".join(f"**{c}: {v:.1%}**" for c, v in skill.items())}.

### Por año (Pinnacle, proporcional)

{fmt(qyear, pct=("% local", "% empate", "% visita"), dec=("Log loss", "RPS"))}

## 4. Calibración del mercado

{cal_summary.to_markdown(index=False)}

![Calibración](figs/02_calibracion.png)

## 5. Sesgo favorito-longshot y ROI ciego por tramo

Apostar 1 unidad a **todas** las selecciones de cada tramo, a cuota de cierre.
"ROI Max" usa la mejor cuota entre casas: **no es alcanzable en la práctica**
(límites, cuentas restringidas, cuotas que se mueven) y se muestra solo como cota superior.

{fmt(by_bucket, pct=("Prob. justa media", "Frecuencia real", "ROI Pinnacle", "ROI Avg", "ROI Max"))}

![Favorito-longshot](figs/03_favorito_longshot.png)

### Por tipo de resultado

{fmt(by_sel, pct=("Prob. justa media", "Frecuencia real", "ROI Pinnacle", "ROI Avg", "ROI Max"))}
"""
    (OUT_DIR / "01_mercado_cierre.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
