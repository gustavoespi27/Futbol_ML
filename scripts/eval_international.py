"""Walk-forward de selecciones: ajuste 2000–2021, prueba 2022–2026 y Pinnacle emparejado de la DB."""

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from footy.betting.devig import proportional
from footy.db.connection import connect
from footy.ingest import international as source
from footy.markets.scoreline import outcome_probs
from footy.models import international


def metrics(probabilities: np.ndarray, outcomes: np.ndarray) -> dict:
    if not len(outcomes):
        return {"n": 0, "log_loss": None, "accuracy": None}
    return {"n": len(outcomes),
            "log_loss": float(-np.log(np.clip(probabilities[np.arange(len(outcomes)), outcomes], 1e-12, 1)).mean()),
            "accuracy": float((probabilities.argmax(axis=1) == outcomes).mean())}


def paired_pinnacle(conn: sqlite3.Connection, model: international.InternationalModel,
                    matches: list[source.InternationalMatch]) -> dict:
    rows = conn.execute("""SELECT m.id,m.kickoff_utc,m.home_goals,m.away_goals,m.round,c.code,
        h.name home,a.name away,o.source,o.captured_at,o.selection,o.price
        FROM matches m JOIN competitions c ON c.id=m.competition_id
        JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id JOIN odds o ON o.match_id=m.id
        WHERE c.type='international' AND m.status='finished' AND m.home_goals IS NOT NULL
          AND m.away_goals IS NOT NULL AND m.kickoff_utc >= '2022-01-01T00:00:00Z'
          AND m.kickoff_utc < '2027-01-01T00:00:00Z' AND o.bookmaker='Pinnacle'
          AND o.market='1X2' AND o.price>1 AND o.captured_at<=m.kickoff_utc
        ORDER BY m.id,o.captured_at DESC,o.source,o.id DESC""").fetchall()
    snapshots: dict[tuple, dict] = {}
    info = {}
    for row in rows:
        info[row["id"]] = row
        snapshots.setdefault((row["id"], row["captured_at"], row["source"]), {})[row["selection"]] = row["price"]
    reference = {(m.kickoff.date(), m.home, m.away): m.neutral for m in matches}
    selected = {}
    for (mid, captured, _), odds in snapshots.items():
        if all(selection in odds for selection in "HDA"):
            selected.setdefault(mid, (captured, odds))
    output = []
    for mid, (captured, odds) in selected.items():
        row = info[mid]
        home, away = model.names.canonical(row["home"]), model.names.canonical(row["away"])
        if home is None or away is None:
            continue
        kickoff = datetime.fromisoformat(row["kickoff_utc"].replace("Z", "+00:00"))
        neutral = source.neutral_policy(row["code"], row["round"])
        for offset in (0, -1, 1):
            key = (kickoff.date() + timedelta(days=offset), home, away)
            if key in reference:
                neutral = reference[key]
                break
        prediction, _, _ = model.predict(home, away, kickoff, neutral)
        market = proportional(np.array([[odds[selection] for selection in "HDA"]]))[0]
        y = 0 if row["home_goals"] > row["away_goals"] else 1 if row["home_goals"] == row["away_goals"] else 2
        output.append({"match_id": mid, "kickoff": row["kickoff_utc"], "captured_at": captured,
                       "home": home, "away": away, "y": y, "model": prediction.tolist(), "pinnacle": market.tolist()})
    y = np.array([row["y"] for row in output], dtype=int)
    return {"model": metrics(np.array([row["model"] for row in output]), y),
            "pinnacle": metrics(np.array([row["pinnacle"] for row in output]), y), "rows": output}


def evaluate(conn: sqlite3.Connection) -> dict:
    model = international.load()
    if model is None:
        raise ValueError("Primero construye el modelo con international.prepare(conn)")
    matches = source.supplement(conn, source.read_results(names=model.names), model.names)
    diff = np.array([model.rating_at(m.home, m.kickoff) - model.rating_at(m.away, m.kickoff)
                     + (100 if m.neutral is False else 0) for m in matches])
    probabilities = outcome_probs(*international.goals(diff, model.intercept, model.slope))
    outcomes = np.array([0 if m.home_goals > m.away_goals else 1 if m.home_goals == m.away_goals else 2
                         for m in matches])
    now = datetime.now(timezone.utc)
    periods = {"ajuste_2000_2021": np.array([2000 <= m.kickoff.year <= 2021 and m.available_at < international.TRAIN_END
                                           for m in matches]),
               "prueba_2022_2026": np.array([2022 <= m.kickoff.year <= 2026 and m.available_at < now for m in matches])}
    friendly = np.array([international.tournament_k(m.tournament) == 20 for m in matches])
    results = {}
    for period, window in periods.items():
        results[period] = {}
        for label, mask in (("todos", window), ("competitivos", window & ~friendly), ("amistosos", window & friendly)):
            results[period][label] = {"model": metrics(probabilities[mask], outcomes[mask]),
                                     "trivial": metrics(np.tile(model.baseline, (int(mask.sum()), 1)), outcomes[mask])}
    return {"version": international.VERSION, "source": source.URL, "data_signature": model.signature,
            "csv_last_date": max(m.kickoff.date().isoformat() for m in matches if m.match_id is None),
            "parameters": {"intercept": model.intercept, "slope": model.slope, "baseline": model.baseline.tolist()},
            "periods": results, "paired_pinnacle": paired_pinnacle(conn, model, matches),
            "limits": ["CSV sin horas: disponibilidad diferida dos días UTC; DB: kickoff + tres horas.",
                       "CSV incluye prórroga en algunos resultados; no garantiza marcador a 90 minutos.",
                       "Sin neutralidad verificada en DB, no se aplica ventaja local salvo eliminatorias o fase UNL.",
                       "No se integra en tracking ni apuestas en papel."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("reports/a3/evaluacion.json"))
    args = parser.parse_args()
    conn = connect()
    try:
        prepared = international.prepare(conn)
        result = evaluate(conn)
    finally:
        conn.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"prepared": prepared, "periods": result["periods"],
                      "paired_pinnacle": {key: value for key, value in result["paired_pinnacle"].items()
                                          if key != "rows"},
                      "parameters": result["parameters"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
