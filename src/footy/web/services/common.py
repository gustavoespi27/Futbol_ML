"""Utilidades compartidas por los servicios del dashboard: redondeo, serialización y fecha de los datos."""

import json

import numpy as np

from footy.db.connection import connect


def _f(x, nd=4):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def _probs(p) -> list[float] | None:
    return None if p is None else [round(float(v), 4) for v in p]


def public(ctx: dict) -> dict:
    return {k: v for k, v in ctx.items() if not k.startswith("_")}


def to_json(obj):
    """json.dumps tolerante a tipos numpy."""
    return json.loads(json.dumps(obj, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def data_through(conn=None) -> dict[str, str]:
    """Fecha del último partido terminado por competición (para avisar si los datos están atrasados)."""
    conn = conn or connect()
    return {r[0]: r[1] for r in conn.execute(
        """SELECT c.code, MAX(m.kickoff_utc) FROM matches m JOIN competitions c ON c.id = m.competition_id
           WHERE m.status = 'finished' GROUP BY c.code""")}
