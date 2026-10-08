"""Predicción de un partido.

Uso:
  python scripts/predict.py --league E0 --home "Liverpool" --away "Arsenal"
  python scripts/predict.py --league E0 --home Liverpool --away Arsenal --odds 2.20 3.60 3.30

Las cuotas (local, empate, visita) son opcionales. Sin ventaja clara: NO APOSTAR.
"""

import argparse
import sys

from footy.prediction.predictor import LeaguePredictor

LABELS = ("local", "empate", "visita")


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def render(r: dict) -> str:
    h, a, m = r["home"], r["away"], r["markets"]
    p = r["p_model"]
    lines = [
        "PARTIDO", f"{h} vs {a}  ({r['league_name']})", "",
        "Probabilidades (ensamble Elo + Dixon-Coles):", "",
        f"{h}: {pct(p[0])}", f"Empate: {pct(p[1])}", f"{a}: {pct(p[2])}", "",
        "Goles esperados:", "", f"{h}: {m['xg_home']:.2f}", f"{a}: {m['xg_away']:.2f}", "",
        "Marcadores más probables:", "",
        *[f"{s}: {pct(q)}" for s, q in m["top_scores"]], "",
        *[f"Over {k}: {pct(v)}   Under {k}: {pct(1 - v)}" for k, v in m["over_under"].items() if k in (1.5, 2.5, 3.5)], "",
        "Ambos marcan:", "", f"Sí: {pct(m['btts_yes'])}", f"No: {pct(m['btts_no'])}", "",
        f"Confianza: {r['confidence']['level']} (partidos recientes del equipo con menos datos: "
        f"{r['confidence']['min_recent_matches']}; desacuerdo Elo vs DC: {r['confidence']['elo_dc_max_diff']:.1%})",
        "(Over/Under, ambos marcan y marcadores salen solo de Dixon-Coles; el 1X2 combina ambos modelos.)",
    ]
    b = r.get("betting")
    if b:
        names = (h, "Empate", a)
        lines += ["", f"CUOTAS (margen de la casa: {b['margin']:.1%})", ""]
        for i, n in enumerate(names):
            lines.append(
                f"{n}: cuota {b['odds'][i]:.2f} | implícita {pct(b['implied'][i])} | justa sin margen "
                f"{pct(b['p_market_fair'][i])} | modelo {pct(p[i])} | edge {b['edge_pp'][i] * 100:+.1f} pp | "
                f"EV modelo {b['ev_model'][i]:+.1%} | EV ajustado al mercado {b['ev_final'][i]:+.1%}")
        best = b["best"]
        lines += ["", f"Umbral de EV (elegido en validación): {b['min_ev']:.0%}"]
        if b["recommend"]:
            lines += ["", "RECOMENDACIÓN:", f"Posible value bet: {names[best]} a {b['odds'][best]:.2f} "
                      f"(EV ajustado {b['ev_final'][best]:+.1%})"]
        else:
            lines += ["", "RECOMENDACIÓN:", "NO APOSTAR (ninguna selección supera el umbral de EV)"]
        lines += [f"Estado de la liga en el backtest: {r['status']}. Ninguna ventaja está garantizada."]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", required=True, help="Código de liga (E0, SP1, ARG, BRA, ...)")
    ap.add_argument("--home", required=True)
    ap.add_argument("--away", required=True)
    ap.add_argument("--odds", nargs=3, type=float, metavar=("LOCAL", "EMPATE", "VISITA"))
    args = ap.parse_args()
    pred = LeaguePredictor(args.league)
    try:
        home, away = pred.find_team(args.home), pred.find_team(args.away)
    except KeyError as e:
        print(e.args[0])
        return 1
    print(render(pred.predict(home, away, tuple(args.odds) if args.odds else None)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
