"""Análisis 06: el apostador profesional en el histórico (football-data.co.uk, 22 ligas europeas).

Simula footy.betting.pro con las cuotas TEMPRANAS (publicadas días antes del partido, cuando un profesional apuesta):
precio justo = Pinnacle temprano sin margen; se apuesta a la mejor cuota entre Bet365, BetWin, William Hill y
1xBet si supera el precio justo en MIN_EDGE (cuota <= MAX_ODDS); CLV contra Pinnacle al cierre.
Regla elegida con 2013-2021 (selección) y evaluada en 2022 en adelante (prueba). Sin Pinnacle no se apuesta.

Uso:  python scripts/pro_backtest.py
Salida: data/processed/pro/backtest.json y docs/analisis/06_profesional.md
"""

import json
import re
import sys
from datetime import datetime

import numpy as np
import pandas as pd

from footy import config
from footy.betting import pro
from footy.ingest import football_data as fd

SOFT = ("B365", "BW", "WH", "1XB")
OUT = config.path("processed") / "pro" / "backtest.json"
DOC = config.PROJECT_ROOT / "docs" / "analisis" / "06_profesional.md"
SELECTION, TEST = (2013, 2021), 2022


def load() -> pd.DataFrame:
    raw = config.path("raw") / fd.SOURCE
    latest = {}
    for f in sorted(raw.glob("*.csv")):
        m = re.match(r"([A-Z0-9]+)_(\d{4})_\d{8}T\d{6}Z\.csv$", f.name)
        if m and m.group(1) in fd.leagues()["main"]:
            latest[(m.group(1), m.group(2))] = f
    frames = []
    for (code, tag), f in latest.items():
        d = pd.read_csv(f, on_bad_lines="skip", encoding_errors="replace", low_memory=False)
        frames.append(d.assign(code=code, season=int("20" + tag[:2])))
    d = pd.concat(frames, ignore_index=True).dropna(subset=["FTHG", "FTAG", "Date"])
    d["date"] = pd.to_datetime(d.Date, dayfirst=True, errors="coerce")
    return d.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def simulate(d: pd.DataFrame) -> pd.DataFrame:
    """Una fila por apuesta de la regla (ordenadas por fecha)."""
    num = lambda c: pd.to_numeric(d[c], errors="coerce").to_numpy() if c in d else np.full(len(d), np.nan)  # noqa: E731
    bets = []
    hg, ag = d.FTHG.astype(float).to_numpy(), d.FTAG.astype(float).to_numpy()
    res = np.select([hg > ag, hg == ag], ["H", "D"], "A")
    cols = {f"{p}{s}": num(f"{p}{s}") for p in ("PS", "PSC", *SOFT) for s in pro.SEL}
    for i in range(len(d)):
        odds = {"Pinnacle": {s: cols[f"PS{s}"][i] for s in pro.SEL}}
        for b in SOFT:
            odds[b] = {s: cols[f"{b}{s}"][i] for s in pro.SEL if not np.isnan(cols[f"{b}{s}"][i])}
        if any(np.isnan(v) for v in odds["Pinnacle"].values()):
            continue
        opps = pro.evaluate(odds)
        chosen = pro.pick({i: opps})
        if not chosen:
            continue
        c = chosen[0]
        closing = {"Pinnacle": {s: cols[f"PSC{s}"][i] for s in pro.SEL}}
        clv = None if any(np.isnan(v) for v in closing["Pinnacle"].values()) else pro.clv(c["odds"], closing, c["sel"])
        bets.append({"date": d.date.iat[i], "season": int(d.season.iat[i]), "code": d.code.iat[i],
                     "sel": c["sel"], "odds": c["odds"], "book": c["book"], "p": c["p_fair"], "edge": c["edge"],
                     "stake": c["stake"], "won": res[i] == c["sel"], "clv": clv})
    return pd.DataFrame(bets)


def summary(b: pd.DataFrame) -> dict:
    if b.empty:
        return {"n": 0}
    prof = np.where(b.won, b.odds - 1, -1.0)
    se = prof.std(ddof=1) / np.sqrt(len(prof)) if len(prof) > 1 else 0
    bank = 100.0
    for s, p in zip(b.stake, prof):
        bank *= 1 + s * p
    clv = b.clv.dropna()
    return {"n": len(b), "hit": round(float(b.won.mean()), 4), "p_mean": round(float(b.p.mean()), 4),
            "odds_mean": round(float(b.odds.mean()), 2), "edge_mean": round(float(b.edge.mean()), 4),
            "yield": round(float(prof.mean()), 4), "ci": [round(float(prof.mean() - 1.96 * se), 4),
                                                          round(float(prof.mean() + 1.96 * se), 4)],
            "units": round(float(prof.sum()), 1), "kelly_bank": round(bank, 1),
            "clv": round(float(clv.mean()), 4) if len(clv) else None,
            "clv_pos": round(float((clv > 0).mean()), 4) if len(clv) else None}


def curve(b: pd.DataFrame) -> list[dict]:
    bank, peak, pts = 100.0, 100.0, []
    for r in b.itertuples():
        bank *= 1 + r.stake * ((r.odds - 1) if r.won else -1)
        peak = max(peak, bank)
        pts.append({"d": r.date.strftime("%Y-%m-%d"), "b": round(bank, 2), "dd": round(1 - bank / peak, 4)})
    step = max(1, len(pts) // 200)
    return pts[::step] + pts[-1:]


def main() -> int:
    d = load()
    b = simulate(d)
    sel = b[(b.season >= SELECTION[0]) & (b.season <= SELECTION[1])]
    test = b[b.season >= TEST]
    rep = {"rules": pro.RULES, "soft_books": ["Bet365", "BetWin", "William Hill", "1xBet"],
           "generated": datetime.now().strftime("%Y-%m-%d"), "matches": int(len(d)),
           "selection": {"period": f"{SELECTION[0]}-{SELECTION[1]}", **summary(sel)},
           "test": {"period": f"{TEST}-{int(d.season.max())}", **summary(test)},
           "by_year": [{"season": int(s), **summary(g)} for s, g in b.groupby("season")],
           "by_sel": [{"sel": s, **summary(g)} for s, g in b.groupby("sel")],
           "max_drawdown": round(max(p["dd"] for p in curve(b)), 4) if len(b) else None,
           "curve": curve(b)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=1, ensure_ascii=False, default=str), encoding="utf-8", newline="\n")
    write_doc(rep)
    print(json.dumps({k: rep[k] for k in ("selection", "test", "max_drawdown")}, indent=1))
    return 0


def miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def write_doc(r: dict) -> None:
    def row(name, s):
        if not s.get("n"):
            return f"| {name} | 0 | | | | | |"
        return (f"| {name} | {s['n']} | {s['hit']:.1%} | {s['odds_mean']:.2f} | {s['yield']:+.1%} "
                f"[{s['ci'][0]:+.1%}; {s['ci'][1]:+.1%}] | {s['clv']:+.1%} | {s['clv_pos']:.0%} |")

    md = [
        "# Análisis 06 — El apostador profesional (value betting contra Pinnacle)", "",
        "*Generado por `scripts/pro_backtest.py`.*", "",
        f"{miles(r['matches'])} partidos de 22 ligas europeas (football-data.co.uk). "
        "Cuotas **tempranas** (días antes del "
        "partido): precio justo = Pinnacle sin margen; se apuesta a la mejor cuota entre Bet365, BetWin, William Hill "
        f"y 1xBet cuando la supera en ≥ {r['rules']['min_edge']:.0%} (cuota ≤ {r['rules']['max_odds']}), una por "
        "partido, ¼ de Kelly con tope de 2% y 10% diario. CLV contra Pinnacle al cierre. Sin Pinnacle no se apuesta "
        "(football-data dejó de publicarlo en 2025-26).", "",
        "Regla elegida con 2013-2021 entre 20 combinaciones de umbral y cuota máxima (la de mejor rendimiento con "
        "≥ 300 apuestas); por eso el rendimiento de selección está inflado. La prueba es 2022 en adelante.", "",
        "| Período | Apuestas | Acierto | Cuota media | Rendimiento [IC95%] | CLV medio | Con CLV > 0 |",
        "|---|---:|---:|---:|---|---:|---:|",
        row(f"Selección {r['selection']['period']}", r["selection"]),
        row(f"Prueba {r['test']['period']}", r["test"]), "",
        "## Por temporada", "",
        "| Temporada | Apuestas | Acierto | Cuota media | Rendimiento [IC95%] | CLV medio | Con CLV > 0 |",
        "|---|---:|---:|---:|---|---:|---:|",
        *[row(str(y["season"]), y) for y in r["by_year"]], "",
        "## Lectura", "",
        "- **CLV positivo y sostenido** mientras hubo referencia de Pinnacle: la mayoría de las apuestas consiguió "
        "mejor precio que el cierre. Es la huella de una ventaja real (las casas blandas corrigen hacia Pinnacle).",
        "- El rendimiento en dinero es ruidoso: con cuotas medias ~3 hacen falta miles de apuestas para separarlo "
        "del azar. El CLV converge mucho antes y es el indicador a seguir.",
        "- Riesgos reales que el histórico no ve: las casas limitan o cierran cuentas ganadoras, las cuotas "
        "tempranas tienen límites de apuesta bajos y la cuota puede cambiar antes de que se coloque la apuesta.", "",
    ]
    DOC.write_text("\n".join(md), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
