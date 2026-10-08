"""Consolida en config/league_models.json los parámetros elegidos en VALIDACIÓN por liga.

Fuente: análisis 04 (con tiros) si existe para la liga; si no, análisis 03.
Los pesos Elo+DC se ajustan con las predicciones walk-forward del período de validación.

Uso:  python scripts/build_league_models.py
"""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import screen_leagues as sl  # noqa: E402

from footy import config  # noqa: E402
from footy.ingest.football_data import leagues  # noqa: E402
from footy.leagues import PARAMS_PATH  # noqa: E402
from footy.models.ensemble import fit_weights  # noqa: E402

SHOTS = config.path("processed") / "shots"

STATUS = {
    "CONFIRMADA": "pasó el criterio pre-registrado, pero sin significancia tras corregir por 38 ligas (seguimiento prospectivo)",
    "candidata (falla en test)": "sin ventaja demostrada (candidata en validación, falló en test)",
    "no": "sin ventaja demostrada",
}


def main() -> int:
    cfg = leagues()
    out = {}
    for code in [*cfg["extra"], *cfg["main"]]:
        src = SHOTS if (SHOTS / f"{code}.json").exists() else sl.CACHE
        if not (src / f"{code}.json").exists():
            continue
        r = json.loads((src / f"{code}.json").read_text(encoding="utf-8"))
        base = json.loads((sl.CACHE / f"{code}.json").read_text(encoding="utf-8"))
        wf = pd.read_csv(src / f"wf_{code}.csv")
        v = wf[(wf.period == "val") & wf[["pin_H", "pin_D", "pin_A"]].notna().all(axis=1)]
        Ps = [v[[f"{m}_pH", f"{m}_pD", f"{m}_pA"]].to_numpy() for m in ("Elo", "Dixon-Coles")]
        out[code] = {
            "dixon_coles": r["dc_params"],
            "elo": r["elo_params"],
            "w_models": fit_weights(Ps, v.y.to_numpy()).round(4).tolist(),
            "w_blend": [round(x, 4) for x in r["w_blend"]],
            "min_ev": r["min_ev"]["Elo+DC+Mercado"],
            "status": STATUS[sl.classify(base)],
            "source": "análisis 04 (tiros)" if src == SHOTS else "análisis 03",
        }
    PARAMS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(out)} ligas -> {PARAMS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
