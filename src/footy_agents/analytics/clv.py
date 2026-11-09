"""CLV por referencia de entrada, sin alterar el cálculo de cierre del motor."""

import json
import sqlite3

import numpy as np
import pandas as pd

from footy.prediction import tracking


def settled_bets(conn: sqlite3.Connection) -> pd.DataFrame:
    _, bets = tracking.evaluate(conn, tracking.ALL_VERSIONS)
    if bets.empty:
        return bets
    marks = ",".join("?" for _ in tracking.ALL_VERSIONS)
    preds = pd.read_sql_query(
        f"""SELECT p.*, m.kickoff_utc AS kickoff, th.name AS home, ta.name AS away
            FROM predictions p JOIN matches m ON m.id=p.match_id
            JOIN teams th ON th.id=m.home_team_id JOIN teams ta ON ta.id=m.away_team_id
            WHERE m.status='finished' AND m.home_goals IS NOT NULL AND p.created_at < m.kickoff_utc
              AND p.model_version IN ({marks})""", conn, params=tracking.ALL_VERSIONS)
    preds = preds.sort_values("created_at").groupby(["match_id", "model_version"]).tail(1)
    refs = []
    # evaluate conserva este mismo orden. No unir por nombres: la base contiene partidos duplicados con IDs distintos.
    for row in preds.to_dict("records"):
        extra = json.loads(row["extra_json"])
        for _ in extra["paper_bets"]:
            refs.append({"match_id": row["match_id"],
                         "market_reference": extra.get("market_reference") or "Sin referencia",
                         "partido": f"{row['home']} vs {row['away']}", "kickoff": row["kickoff"],
                         "model_version": row["model_version"]})
    refs = pd.DataFrame(refs)
    keys = ["partido", "kickoff", "model_version"]
    if not refs[keys].equals(bets[keys]):
        raise ValueError("Cambió el orden del contrato de tracking.evaluate; no se pueden atribuir referencias")
    return pd.concat([bets, refs[["match_id", "market_reference"]]], axis=1)


def summarize(bets: pd.DataFrame, repetitions: int = 2000, seed: int = 42) -> list[dict]:
    if bets.empty:
        return []
    rng = np.random.default_rng(seed)
    rows = []
    for reference, group in bets.groupby("market_reference", dropna=False):
        valid = group[group.clv.notna()]
        # Bootstrap por partido: no tratar varias selecciones/versiones del mismo encuentro como independientes.
        clusters = valid.groupby("match_id").clv.agg(["sum", "count"])
        interval = None
        if len(clusters) >= 2:
            values = clusters.to_numpy()
            samples = rng.integers(0, len(values), size=(repetitions, len(values)))
            sampled = values[samples].sum(axis=1)
            interval = np.quantile(sampled[:, 0] / sampled[:, 1], [0.025, 0.975]).tolist()
        rows.append({"referencia": reference, "n": len(group), "partidos": group.match_id.nunique(),
                     "n_clv": len(valid), "clv": float(valid.clv.mean()) if len(valid) else None,
                     "yield": float(group.profit.mean()), "ic95": interval})
    return rows


def markdown(rows: list[dict]) -> str:
    lines = ["# CLV por referencia de entrada", "",
             "Se reutiliza tracking.evaluate con todas las versiones. Yield por unidad plana; CLV calculado "
             "por el motor contra su referencia de cierre disponible, que puede diferir de la de entrada.", "",
             "IC95% percentil: 2.000 remuestreos por partido, semilla 42. Es descriptivo; no demuestra causalidad "
             "ni controla diferencias de liga, fecha o versión. Un mismo partido puede aparecer en varios grupos.", "",
             "| Referencia | Apuestas | Partidos | Con CLV | CLV medio | IC95% CLV | Yield |",
             "|---|---:|---:|---:|---:|---|---:|"]
    for row in rows:
        clv = f"{row['clv']:+.2%}" if row["clv"] is not None else "Sin dato"
        ci = " / ".join(f"{v:+.2%}" for v in row["ic95"]) if row["ic95"] else "No estimable"
        lines.append(f"| {row['referencia']} | {row['n']} | {row['partidos']} | {row['n_clv']} | "
                     f"{clv} | {ci} | {row['yield']:+.2%} |")
    lines += ["", "Los tamaños corresponden a apuestas liquidadas, no a todas las predicciones que propusieron "
              "apuestas. La muestra de Pinnacle es insuficiente para una conclusión estadística, incluso si "
              "hay dos predicciones de entrada con esa referencia. No se aprueba ni ejecuta F3c.", ""]
    return "\n".join(lines)
