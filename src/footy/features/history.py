"""Variables del historial de los equipos para el modelo de machine learning.

Para cada partido (terminado o programado) se calculan, con los partidos ANTERIORES de cada equipo en cualquier
competición de la base (los ascendidos llegan con su historial de la categoría inferior):

- forma: puntos, goles a favor/en contra, tiros y tiros al arco en los últimos 5 y 10 partidos y con media
  exponencial; forma específica como local (equipo local) y como visita (equipo visitante);
- temporada: puntos por partido y diferencia de gol por partido en la temporada en curso;
- rachas (invicto / sin ganar), descanso en días y experiencia (partidos en la base);
- enfrentamientos directos (últimos 6);
- contexto de la liga: % de victorias locales, empates y goles por partido en sus últimos 300 partidos.

El cálculo recorre los partidos en orden de kickoff y actualiza el historial después de cada partido terminado,
así que ninguna variable usa información del propio partido ni posterior.
"""

import sqlite3
from collections import defaultdict, deque

import numpy as np
import pandas as pd

WINDOW = 10
EWM_ALPHA = 0.15
LEAGUE_WINDOW = 300
H2H_WINDOW = 6

# Atributos por partido guardados en el historial de cada equipo.
_FIELDS = ("gf", "ga", "pts", "sf", "sa", "tf", "ta")      # goles, puntos, tiros al arco (s), tiros (t)


def load_all_matches(conn: sqlite3.Connection) -> pd.DataFrame:
    """Todos los partidos terminados y programados, con tiros si existen. Una fila por partido."""
    m = pd.read_sql_query(
        """SELECT m.id AS match_id, c.code AS comp, m.season, m.kickoff_utc, m.status,
                  m.home_team_id AS home_id, m.away_team_id AS away_id, m.home_goals, m.away_goals
           FROM matches m JOIN competitions c ON c.id = m.competition_id
           WHERE m.status IN ('finished', 'scheduled')
           ORDER BY m.kickoff_utc, m.id""", conn)
    st = pd.read_sql_query(
        """SELECT match_id, team_id, stat, value FROM team_match_stats
           WHERE stat IN ('total_shots', 'shots_on_goal')""", conn).drop_duplicates(["match_id", "team_id", "stat"])
    wide = st.pivot_table(index=["match_id", "team_id"], columns="stat", values="value")
    for side, col in (("h", "home_id"), ("a", "away_id")):
        part = wide.rename(columns={"total_shots": f"{side}_shots", "shots_on_goal": f"{side}_sot"})
        m = m.merge(part, left_on=["match_id", col], right_index=True, how="left")
    for c in ("h_shots", "a_shots", "h_sot", "a_sot"):
        if c not in m:
            m[c] = np.nan
    m["kickoff"] = pd.to_datetime(m.kickoff_utc, utc=True)
    return m.reset_index(drop=True)


def _season_key(row) -> str:
    return f"{row.comp}|{row.season}"


_FORM_FIELDS = ("pts", "gf", "ga", "sf", "sa", "tf", "ta")
_FIELD_IDX = {f: i for i, f in enumerate(_FIELDS)}


def _known(v) -> bool:
    return v is not None and v == v                      # v == v es False solo para NaN


def _mean(values) -> float:
    """Media de una lista corta en Python puro: con ≤ 10 valores enteros es exacta e igual a np.mean, y evita el
    costo fijo de NumPy (más de un millón de llamadas al recorrer toda la base)."""
    return sum(values) / len(values) if values else np.nan


def _team_feats(hist: deque, ewm: dict, prefix: str) -> dict:
    """hist: tuplas en el orden de _FIELDS, solo de partidos anteriores."""
    out = {}
    items = list(hist)
    for n in (5, WINDOW):
        last = items[-n:]
        for f in _FORM_FIELDS:
            i = _FIELD_IDX[f]
            out[f"{prefix}{f}_{n}"] = float(_mean([x[i] for x in last if _known(x[i])])) if last else np.nan
    for f in ("pts", "gf", "ga", "sf", "sa"):
        out[f"{prefix}{f}_ewm"] = ewm.get(f, np.nan)
    return out


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """df: salida de load_all_matches (ordenada por kickoff). Devuelve df + columnas de variables."""
    hist: dict[int, deque] = defaultdict(lambda: deque(maxlen=WINDOW))
    venue_hist: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=5))
    ewm: dict[int, dict] = defaultdict(dict)
    last_date: dict[int, pd.Timestamp] = {}
    n_played: dict[int, int] = defaultdict(int)
    season: dict[tuple, list] = defaultdict(lambda: [0, 0, 0.0])          # partidos, puntos, dif. gol
    streak: dict[int, list] = defaultdict(lambda: [0, 0])                 # invicto, sin ganar
    h2h: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=H2H_WINDOW))
    league: dict[str, deque] = defaultdict(lambda: deque(maxlen=LEAGUE_WINDOW))
    league_sum: dict[str, list] = defaultdict(lambda: [0, 0, 0])          # sumas móviles: local gana, empate, goles

    rows = []
    for r in df.itertuples(index=False):
        h, a, sk = r.home_id, r.away_id, _season_key(r)
        f = {"match_id": r.match_id}
        f.update(_team_feats(hist[h], ewm[h], "h_"))
        f.update(_team_feats(hist[a], ewm[a], "a_"))
        for side, team, venue in (("h", h, "home"), ("a", a, "away")):
            vh = venue_hist[(team, venue)]
            f[f"{side}_venue_pts5"] = float(_mean([x[0] for x in vh]))
            f[f"{side}_venue_gf5"] = float(_mean([x[1] for x in vh]))
            f[f"{side}_venue_ga5"] = float(_mean([x[2] for x in vh]))
            s = season[(team, sk)]
            f[f"{side}_season_n"] = s[0]
            f[f"{side}_season_ppg"] = s[1] / s[0] if s[0] else np.nan
            f[f"{side}_season_gd"] = s[2] / s[0] if s[0] else np.nan
            f[f"{side}_unbeaten"], f[f"{side}_winless"] = streak[team]
            f[f"{side}_rest"] = min((r.kickoff - last_date[team]).days, 30) if team in last_date else np.nan
            f[f"{side}_exp"] = min(n_played[team], 200)
        hh = h2h[(min(h, a), max(h, a))]
        if hh:
            pts = [p if home == h else (3 - p if p != 1 else 1) for home, p, gd in hh]
            gds = [gd if home == h else -gd for home, p, gd in hh]
            f["h2h_n"], f["h2h_pts"], f["h2h_gd"] = len(hh), float(_mean(pts)), float(_mean(gds))
        else:
            f["h2h_n"], f["h2h_pts"], f["h2h_gd"] = 0, np.nan, np.nan
        lg = league[r.comp]
        if lg:
            n_lg, tot = len(lg), league_sum[r.comp]
            f["lg_home"], f["lg_draw"], f["lg_goals"] = tot[0] / n_lg, tot[1] / n_lg, tot[2] / n_lg
        else:
            f["lg_home"] = f["lg_draw"] = f["lg_goals"] = np.nan
        rows.append(f)

        if r.status != "finished" or pd.isna(r.home_goals):
            continue
        hg, ag = int(r.home_goals), int(r.away_goals)
        ph = 3 if hg > ag else 1 if hg == ag else 0
        pa = 3 if ag > hg else 1 if hg == ag else 0
        for team, gf, ga, pts, sf, sa, tf, ta, venue in (
                (h, hg, ag, ph, r.h_sot, r.a_sot, r.h_shots, r.a_shots, "home"),
                (a, ag, hg, pa, r.a_sot, r.h_sot, r.a_shots, r.h_shots, "away")):
            rec = (gf, ga, pts, sf, sa, tf, ta)                  # orden de _FIELDS
            hist[team].append(rec)
            venue_hist[(team, venue)].append((pts, gf, ga))
            e = ewm[team]
            for k in ("pts", "gf", "ga", "sf", "sa"):
                v = rec[_FIELD_IDX[k]]
                if not _known(v):
                    continue
                e[k] = v if k not in e or np.isnan(e[k]) else (1 - EWM_ALPHA) * e[k] + EWM_ALPHA * v
            s = season[(team, sk)]
            s[0] += 1
            s[1] += pts
            s[2] += gf - ga
            st = streak[team]
            st[0] = st[0] + 1 if pts > 0 else 0
            st[1] = st[1] + 1 if pts < 3 else 0
            last_date[team] = r.kickoff
            n_played[team] += 1
        h2h[(min(h, a), max(h, a))].append((h, ph, hg - ag))
        lg, tot, new = league[r.comp], league_sum[r.comp], (int(hg > ag), int(hg == ag), hg + ag)
        if len(lg) == lg.maxlen:                         # sale el partido más antiguo de la ventana
            tot[:] = [t - o for t, o in zip(tot, lg[0])]
        lg.append(new)
        tot[:] = [t + x for t, x in zip(tot, new)]

    # Todas las variables en float64 (los contadores también): tipos consistentes para el modelo y sin
    # conversiones implícitas de Pandas al combinar con NaN.
    feats = pd.DataFrame(rows).astype({c: "float64" for c in rows[0] if c != "match_id"} if rows else {})
    out = df.merge(feats, on="match_id", how="left")
    # Diferencias local - visita de las variables principales (los árboles las aprovechan mejor así).
    for base in ("pts_5", "pts_10", "gf_10", "ga_10", "sf_10", "sa_10", "pts_ewm", "gf_ewm", "ga_ewm",
                 "sf_ewm", "sa_ewm", "season_ppg", "season_gd", "rest", "exp"):
        out[f"d_{base}"] = out[f"h_{base}"] - out[f"a_{base}"]
    return out


# Estadísticas del PROPIO partido (se conocen al terminar): nunca pueden ser variables.
SAME_MATCH = {"h_shots", "a_shots", "h_sot", "a_sot"}
PREFIXES = ("h_", "a_", "d_", "h2h_", "lg_")


def feature_columns(df: pd.DataFrame) -> list[str]:
    """Solo las variables creadas por build_features (lista blanca por prefijo). Cualquier otra columna que se
    una al DataFrame (cuotas, probabilidades de mercado, resultados) queda fuera: evita fugas de información."""
    return [c for c in df.columns if c.startswith(PREFIXES) and c not in SAME_MATCH]
