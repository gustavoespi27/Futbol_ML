"""Análisis 05: modelos de machine learning sobre el historial de los equipos.

1. Variables del historial (footy.features.history) para los 173 mil partidos de la base.
2. Gradient boosting con pérdida Poisson para los goles del local (λ) y de la visita (μ); 1X2, más de 2,5 goles y
   ambos marcan salen de la misma matriz de marcadores. Dos variantes: solo historial e historial + Elo/Dixon-Coles.
   Hiperparámetros y rho elegidos en VALID (2024-25); modelo final con 2014-2025.
3. Mezcla con el mercado (pesos ajustados en VALID).
4. Evaluación única en 2026: calidad de las probabilidades, alta confianza y apuestas con la regla de sugerencias.

Uso:  python scripts/train_ml.py                (unos 15-20 minutos)
      python scripts/train_ml.py --eval         (solo evaluación, con los modelos ya entrenados)
      python scripts/train_ml.py --production   (reentrena con todos los datos hasta hoy para predecir)
Salida: artifacts/ml/ (modelos), data/processed/ml/report.json, docs/analisis/05_ml.md
"""

import json
import sys
import time

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.inspection import permutation_importance

from footy import config
from footy.betting import suggestions as sg
from footy.data import load_ou_closing
from footy.db.connection import connect
from footy.evaluation import live
from footy.features.history import build_features, load_all_matches
from footy.leagues import load_params
from footy.markets.combos import logit
from footy.models import ml
from footy.models.ensemble import fit_weights

OUT = config.path("processed") / "ml"
DOC = config.PROJECT_ROOT / "docs" / "analisis" / "05_ml.md"
WF_COLS = [*ml.ELO_DC_COLS, "Mercado_pH", "Mercado_pD", "Mercado_pA", "b365_H", "b365_D", "b365_A"]


def log(*a):
    print(*a, flush=True)


def assemble(conn) -> pd.DataFrame:
    t = time.time()
    df = build_features(load_all_matches(conn))
    log(f"variables: {df.shape} en {time.time() - t:.0f}s")
    wf = []
    for code in load_params():
        d = live.read_wf(code)
        if d is not None:
            wf.append(d[["match_id", *[c for c in WF_COLS if c in d]]])
    df = df.merge(pd.concat(wf).drop_duplicates("match_id"), on="match_id", how="left")
    ou = load_ou_closing(conn, df.match_id[df.status == "finished"])
    return df.merge(ou, left_on="match_id", right_index=True, how="left")


def fit_binary_blend(p_ml, p_mkt, y) -> list[float]:
    def nll(w):
        p = np.clip(1 / (1 + np.exp(-(w[0] * logit(p_ml) + w[1] * logit(p_mkt) + w[2]))), 1e-9, 1 - 1e-9)
        return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    return minimize(nll, [0.2, 0.8, 0.0], method="L-BFGS-B", bounds=[(0, 3), (0, 3), (-2, 2)]).x.round(4).tolist()


def ll(P, y):
    return ml._logloss(np.asarray(P, dtype=float), np.asarray(y))


def acc(P, y):
    P = np.asarray(P, dtype=float)
    return float((P.argmax(1) == y).mean()) if P.ndim == 2 else float(((P > 0.5) == y).mean())


def ci(x):
    return live._ci(np.asarray(x, dtype=float))


def bets(df: pd.DataFrame, probs: dict[str, np.ndarray]) -> dict:
    """Regla de sugerencias (valor >= 3%, cuota 1,30-4,0, p >= 25%) a cuota de cierre Bet365, una por partido."""
    hg, ag = df.home_goals.to_numpy(float), df.away_goals.to_numpy(float)
    odds = {k: df[c].to_numpy(float) for k, c in
            (("1", "b365_H"), ("X", "b365_D"), ("2", "b365_A"), ("O2.5", "b365_over"), ("U2.5", "b365_under"))}
    hit = {"1": hg > ag, "X": hg == ag, "2": hg < ag, "O2.5": hg + ag > 2.5, "U2.5": hg + ag < 2.5}
    cands = []
    for i in range(len(df)):
        for k, p in probs.items():
            o = odds[k][i]
            if not np.isnan(o) and not np.isnan(p[i]):
                cands.append({"match": i, "key": k, "p": float(p[i]), "odds": float(o), "hit": bool(hit[k][i])})
    picks = sg.pick_singles(cands)
    if not picks:
        return {"n": 0}
    prof = np.array([p["odds"] - 1 if p["hit"] else -1.0 for p in picks])
    return {"n": len(picks), "hit": round(float(np.mean([p["hit"] for p in picks])), 4),
            "p_mean": round(float(np.mean([p["p"] for p in picks])), 4), "yield": round(float(prof.mean()), 4),
            "ci": ci(prof), "odds_mean": round(float(np.mean([p["odds"] for p in picks])), 2)}


def confidence(P: np.ndarray, y: np.ndarray, odds: np.ndarray) -> list[dict]:
    """Pronóstico = resultado más probable. Acierto real y rendimiento apostando a él, por nivel de confianza."""
    top, k = P.max(1), P.argmax(1)
    o = odds[np.arange(len(k)), k]
    out = []
    for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)):
        m = (top >= lo) & (top < hi) & ~np.isnan(o)
        if m.sum() >= 20:
            prof = np.where(k[m] == y[m], o[m] - 1, -1.0)
            out.append({"range": f"{int(lo * 100)}–{min(int(hi * 100), 100)}%", "n": int(m.sum()),
                        "pred": round(float(top[m].mean()), 4), "hit": round(float((k[m] == y[m]).mean()), 4),
                        "odds_mean": round(float(np.nanmean(o[m])), 2), "yield": round(float(prof.mean()), 4),
                        "ci": ci(prof)})
    return out


def main() -> int:
    conn = connect()
    OUT.mkdir(parents=True, exist_ok=True)
    df = assemble(conn)
    fin = df[df.status == "finished"].reset_index(drop=True)
    y_all = ml.targets(fin)
    k = fin.kickoff_utc
    va = ((k >= ml.VALID_FROM) & (k < ml.TEST_FROM)).to_numpy()

    if "--production" in sys.argv:
        model, meta = ml.load()
        prod = ml.refit_production(fin, model)
        ml.save(prod, {**meta, "trained_until": fin.kickoff_utc.max()[:10], "production": True})
        log(f"modelos de producción entrenados con {len(fin):,} partidos hasta {fin.kickoff_utc.max()[:10]}")
        return 0
    if "--eval" in sys.argv:                     # reutiliza el modelo ya entrenado
        model, meta = ml.load()
        if meta.get("production"):               # ya vio 2026: evaluarlo en 2026 sería hacer trampa
            log("El modelo guardado es de producción (entrenado con 2026). Reentrena sin --eval para evaluar.")
            return 1
        blend, valid_ll = meta["blend"], meta["valid_logloss"]
    else:
        model, blend, valid_ll = train(fin, y_all, va)
    evaluate(fin, y_all, k, va, model, blend, valid_ll)
    return 0


def train(fin, y_all, va):
    cand = {use: ml.fit(fin, use, log) for use in (False, True)}
    # Variante elegida por log loss 1X2 en VALID sobre las mismas filas (las que tienen Elo/DC).
    has = fin[ml.ELO_DC_COLS[0]].notna().to_numpy()
    common = va & has
    lls = {use: ll(_valid_pred(c, va, has, use)["1x2"][common[va]], y_all["1x2"][common]) for use, c in cand.items()}
    use = min(lls, key=lls.get)
    model, _ = cand[use]
    valid_ll = {"historial": lls[False], "historial+elo_dc": lls[True], "elegida": cand[use][0].valid_logloss}
    log(f"VALID 1X2 historial={lls[False]:.5f} historial+elo/dc={lls[True]:.5f} -> elo_dc={use} (rho={model.rho})")
    # Mezcla con el mercado (en VALID, con predicciones del modelo de solo TRAIN).
    p_val = _valid_pred(cand[use], va, has, use)
    mk = fin.loc[va, ["Mercado_pH", "Mercado_pD", "Mercado_pA"]].to_numpy()
    ok = ~np.isnan(mk).any(1) & ~np.isnan(p_val["1x2"]).any(1)
    blend = {"1x2": fit_weights([p_val["1x2"][ok], mk[ok]], y_all["1x2"][va][ok], nonneg=True).round(4).tolist()}
    mo = fin.loc[va, "p_over"].to_numpy()
    ok = ~np.isnan(mo) & ~np.isnan(p_val["over25"])
    blend["over25"] = fit_binary_blend(p_val["over25"][ok], mo[ok], y_all["over25"][va][ok])
    log(f"  mezcla con mercado: {blend}")
    ml.save(model, {"model": "poisson_goals", "use_elo_dc": use, "rho": model.rho, "blend": blend,
                    "valid_logloss": valid_ll, "trained_until": ml.TEST_FROM,
                    "report": "data/processed/ml/report.json"})
    return model, blend, valid_ll


def evaluate(fin, y_all, k, va, model, blend, valid_ll):

    # --- Evaluación única en 2026 -------------------------------------------------------------
    te = (k >= ml.TEST_FROM).to_numpy()
    T = fin[te].reset_index(drop=True)
    yT = {t: v[te] for t, v in y_all.items()}
    P = model.predict(T)
    lf = live.live_frame().set_index("match_id")
    cur = T.match_id.map(lambda i: i in lf.index).to_numpy()
    rep = {"periods": {"train": [ml.TRAIN_FROM, ml.VALID_FROM], "valid": [ml.VALID_FROM, ml.TEST_FROM],
                       "test": [ml.TEST_FROM, T.kickoff_utc.max()[:10]]},
           "n_features": int(len(ml.design(fin.head(1), model.use_elo_dc, model.comps).columns)),
           "n_train": int(((k >= ml.TRAIN_FROM) & (k < ml.TEST_FROM)).sum()), "n_test": int(te.sum()),
           "model": "poisson_goals", "use_elo_dc": model.use_elo_dc, "rho": model.rho, "blend": blend,
           "valid_logloss": valid_ll,
           "params": {s: {"params": model.params[s], "n_iter": model.n_iter[s]} for s in ml.SIDES}}

    # 1X2: mismas filas para todos (con mercado y con predicción del modelo actual)
    mk = T[["Mercado_pH", "Mercado_pD", "Mercado_pA"]].to_numpy()
    rows = cur & ~np.isnan(mk).any(1)
    of = lf.loc[T.match_id[rows], ["of_H", "of_D", "of_A"]].to_numpy()
    mo = lf.loc[T.match_id[rows], ["mo_H", "mo_D", "mo_A"]].to_numpy()
    p_ml = P["1x2"][rows]
    p_bl = ml.blend_1x2(p_ml, mk[rows], blend["1x2"])
    y = yT["1x2"][rows]
    rep["x12"] = {"n": int(rows.sum()), **{
        name: {"logloss": round(ll(p, y), 5), "acc": round(acc(p, y), 4)} for name, p in (
            ("mercado", mk[rows]), ("elo_dc", mo), ("oficial_actual", of), ("ml", p_ml), ("ml_mercado", p_bl))}}
    odds = T.loc[rows, ["b365_H", "b365_D", "b365_A"]].to_numpy(float)
    rep["confidence"] = {"ml": confidence(p_ml, y, odds), "ml_mercado": confidence(p_bl, y, odds),
                         "mercado": confidence(mk[rows], y, odds)}

    # Más/menos 2,5 y ambos marcan
    ou_rows = rows & T.p_over.notna().to_numpy()
    po_ml = P["over25"][ou_rows]
    po_bl = ml.blend_binary(po_ml, T.p_over.to_numpy()[ou_rows], blend["over25"])
    yo = yT["over25"][ou_rows]
    ids = T.match_id[ou_rows]
    rep["over25"] = {"n": int(ou_rows.sum()), **{
        name: {"logloss": round(ll(p, yo), 5), "acc": round(acc(p, yo), 4)} for name, p in (
            ("mercado", T.p_over.to_numpy()[ou_rows]), ("dixon_coles", lf.loc[ids, "over_dc"].to_numpy()),
            ("oficial_actual", lf.loc[ids, "over_off"].to_numpy()), ("ml", po_ml), ("ml_mercado", po_bl))}}
    yb = yT["btts"][rows]
    base = np.full(len(yb), fin.loc[va, "home_goals"].gt(0).mul(fin.loc[va, "away_goals"].gt(0)).mean())
    pb = P["btts"][rows]
    rep["btts"] = {"n": int(rows.sum()),
                   "frecuencia_historica": {"logloss": round(ll(base, yb), 5), "acc": round(acc(base, yb), 4)},
                   "ml": {"logloss": round(ll(pb, yb), 5), "acc": round(acc(pb, yb), 4)}}

    # Apuestas con la regla de sugerencias
    Tb = T[rows].reset_index(drop=True)
    over_ml = np.where(ou_rows[rows], P["over25"][rows], np.nan)
    over_bl = np.full(len(Tb), np.nan)
    over_bl[ou_rows[rows]] = po_bl
    mk_over = Tb.p_over.to_numpy()
    rep["bets"] = {
        "ml": bets(Tb, {"1": p_ml[:, 0], "X": p_ml[:, 1], "2": p_ml[:, 2],
                        "O2.5": over_ml, "U2.5": 1 - over_ml}),
        "ml_mercado": bets(Tb, {"1": p_bl[:, 0], "X": p_bl[:, 1], "2": p_bl[:, 2],
                                "O2.5": over_bl, "U2.5": 1 - over_bl}),
        "oficial_actual": bets(Tb, {"1": of[:, 0], "X": of[:, 1], "2": of[:, 2],
                                    "O2.5": lf.loc[Tb.match_id, "over_off"].to_numpy(),
                                    "U2.5": 1 - lf.loc[Tb.match_id, "over_off"].to_numpy()}),
        "mercado": bets(Tb, {"1": mk[rows][:, 0], "X": mk[rows][:, 1], "2": mk[rows][:, 2],
                             "O2.5": mk_over, "U2.5": 1 - mk_over}),
    }

    # Por liga (log loss ML+mercado vs mercado)
    per = []
    for code, g in pd.Series(np.arange(rows.sum())).groupby(T.comp[rows].to_numpy()):
        i = g.to_numpy()
        if len(i) >= 60:
            per.append({"code": code, "n": len(i), "ml": round(ll(p_ml[i], y[i]), 4),
                        "ml_mercado": round(ll(p_bl[i], y[i]), 4),
                        "mercado": round(ll(mk[rows][i], y[i]), 4), "acc_ml": round(acc(p_ml[i], y[i]), 4),
                        "acc_mercado": round(acc(mk[rows][i], y[i]), 4)})
    rep["per_league"] = per

    # Qué variables pesan más (permutación sobre una muestra de VALID, goles esperados del local)
    smp = fin[va].sample(min(6000, int(va.sum())), random_state=0)
    Xs = ml.design(smp, model.use_elo_dc, model.comps)
    imp = permutation_importance(model.models["lam"], Xs, smp.home_goals.to_numpy(float),
                                 scoring="neg_mean_poisson_deviance", n_repeats=3, random_state=0)
    order = np.argsort(imp.importances_mean)[::-1][:15]
    rep["importance"] = [{"feature": Xs.columns[i], "importance": round(float(imp.importances_mean[i]), 5)}
                         for i in order]

    (OUT / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
    write_doc(rep)
    log(json.dumps({key: rep[key] for key in ("x12", "over25", "btts", "bets")}, indent=1, ensure_ascii=False))


def _valid_pred(cand, va, has, use):
    """Probabilidades de VALID del modelo de solo TRAIN, alineadas a todas las filas de VALID (NaN si no aplica)."""
    _, P = cand
    rows = (va & has if use else va)[va]
    out = {}
    for t, p in P.items():
        o = np.full((va.sum(), 3), np.nan) if t == "1x2" else np.full(va.sum(), np.nan)
        o[rows] = p
        out[t] = o
    return out


def _ci_txt(x: dict) -> str:
    c = x.get("ci")
    return f"[{c[0]:+.1%}; {c[1]:+.1%}]" if c else ""


def miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def write_doc(r: dict) -> None:
    def tbl(block, names):
        lines = ["| Fuente | Log loss | Acierto |", "|---|---:|---:|"]
        for key, label in names:
            lines.append(f"| {label} | {block[key]['logloss']:.4f} | {block[key]['acc']:.1%} |")
        return "\n".join(lines)

    b = r["bets"]
    md = [
        "# Análisis 05 — Machine learning sobre el historial de los equipos", "",
        "*Generado por `scripts/train_ml.py`.*", "",
        f"Gradient boosting con pérdida Poisson y {r['n_features']} variables del historial (forma, tiros, localía, "
        "temporada, rachas, descanso, enfrentamientos directos, contexto de liga) + liga, y opcionalmente las "
        "predicciones de Elo y Dixon-Coles. Predice los goles esperados del local (λ) y de la visita (μ); 1X2, "
        f"más/menos de 2,5 y ambos marcan salen de la misma matriz de marcadores (rho = {r['rho']}), "
        "así que son coherentes. "
        f"Entrenamiento {r['periods']['train'][0]} → {r['periods']['valid'][1]} "
        f"({miles(r['n_train'])} partidos), hiperparámetros elegidos en {r['periods']['valid'][0][:4]}-2025, "
        f"evaluación única en 2026 ({miles(r['n_test'])} partidos).", "",
        "Variante elegida en validación (log loss 1X2): "
        + ("historial + Elo/Dixon-Coles" if r["use_elo_dc"] else "solo historial") + ".", "",
        f"## Resultado 1X2 en 2026 ({miles(r['x12']['n'])} partidos)", "",
        tbl(r["x12"], [("mercado", "Mercado (cierre sin margen)"), ("elo_dc", "Elo + Dixon-Coles"),
                       ("oficial_actual", "Oficial actual (Elo+DC+mercado)"), ("ml", "ML"),
                       ("ml_mercado", "ML + mercado")]), "",
        f"## Más/menos de 2,5 goles en 2026 ({miles(r['over25']['n'])} partidos)", "",
        tbl(r["over25"], [("mercado", "Mercado"), ("dixon_coles", "Dixon-Coles"), ("oficial_actual", "Oficial actual"),
                          ("ml", "ML"), ("ml_mercado", "ML + mercado")]), "",
        "## Ambos marcan en 2026", "",
        tbl(r["btts"], [("frecuencia_historica", "Frecuencia histórica"), ("ml", "ML")]), "",
        "## Pronósticos de alta confianza (ML + mercado, resultado más probable)", "",
        "| Confianza | Partidos | Esperado | Acierto real | Cuota media | Rendimiento apostando |",
        "|---|---:|---:|---:|---:|---:|",
        *[f"| {c['range']} | {c['n']} | {c['pred']:.1%} | {c['hit']:.1%} | {c['odds_mean']:.2f} | {c['yield']:+.1%} |"
          for c in r["confidence"]["ml_mercado"]], "",
        "## Apuestas con la regla de sugerencias (valor ≥ 3%, cuota 1,30-4,0), cierre Bet365", "",
        "| Probabilidades | Apuestas | Acierto | Esperado | Rendimiento | IC95% |", "|---|---:|---:|---:|---:|---|",
        *[f"| {name} | {x['n']} | {x.get('hit', 0):.1%} | {x.get('p_mean', 0):.1%} | {x.get('yield', 0):+.1%} | "
          f"{_ci_txt(x)} |"
          for name, x in (("ML", b["ml"]), ("ML + mercado", b["ml_mercado"]), ("Oficial actual", b["oficial_actual"]),
                          ("Mercado (control)", b["mercado"]))], "",
        "## Conclusión", "",
        "- El ML mejora a Elo + Dixon-Coles en 1X2, más/menos de 2,5 y ambos marcan, pero la mejora es pequeña.",
        f"- No alcanza al mercado: al combinarlos con pesos ajustados en validación, el ML recibe peso "
        f"{r['blend']['1x2'][0]} en 1X2 frente a {r['blend']['1x2'][1]} del mercado. La leve mejora de "
        "\"ML + mercado\" sobre el mercado viene de afinar las probabilidades del mercado, no del ML.",
        "- Apostar con las probabilidades del ML pierde; las estrategias que salen positivas tienen pocos casos e "
        "intervalos que incluyen pérdidas grandes.",
        "- El historial público (resultados, goles, tiros) ya está incorporado en las cuotas. Para superar al mercado "
        "harían falta datos que este no refleje todavía: alineaciones confirmadas, lesiones, cuotas tempranas.",
        "- Uso en el sistema: el ML reemplaza a Elo + Dixon-Coles como modelo propio (partidos sin cuotas, "
        "comparación modelo vs mercado y probabilidad de ambos marcan en la matriz de marcadores).", "",
        "## Variables más influyentes (goles esperados del local)", "",
        *[f"{i + 1}. `{x['feature']}` ({x['importance']:.4f})" for i, x in enumerate(r["importance"])], "",
    ]
    DOC.write_text("\n".join(md), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
