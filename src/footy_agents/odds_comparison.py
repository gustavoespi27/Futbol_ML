"""Comparación de precios ofrecidos; solo Pinnacle sin margen aporta probabilidades justas."""

import math
import sqlite3
from datetime import datetime, timezone

from footy.betting import pro
from footy_agents.calendar import local_fields


def latest_books(conn: sqlite3.Connection, match_id: int, now: datetime | None = None) -> dict[str, dict]:
    now = now or datetime.now(timezone.utc)
    rows = conn.execute(
        """SELECT bookmaker,selection,price,captured_at FROM (
        SELECT o.*,ROW_NUMBER() OVER(PARTITION BY bookmaker,selection ORDER BY captured_at DESC,o.id DESC) AS n
        FROM odds o JOIN matches m ON m.id=o.match_id
        WHERE o.match_id=? AND market='1X2' AND line=0 AND is_closing=0
          AND captured_at<=? AND captured_at<m.kickoff_utc
    ) WHERE n=1 ORDER BY bookmaker,selection""",
        (match_id, now.strftime("%Y-%m-%dT%H:%M:%SZ")),
    ).fetchall()
    books: dict[str, dict] = {}
    for book, selection, price, _ in rows:
        if selection in pro.SEL and math.isfinite(price) and price > 1:
            books.setdefault(book, {})[selection] = price
    return books


def compare(conn: sqlite3.Connection, match_id: int, now: datetime | None = None) -> dict:
    match = conn.execute(
        """SELECT h.name,a.name,m.kickoff_utc FROM matches m
        JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id WHERE m.id=?""",
        (match_id,),
    ).fetchone()
    if not match:
        raise ValueError("Partido no encontrado")
    books = latest_books(conn, match_id, now)
    p = pro.fair_1x2(books)
    best = pro.best_prices(books)
    margins = {
        book: round(sum(1 / prices[s] for s in pro.SEL) - 1, 6)
        for book, prices in books.items()
        if all(s in prices for s in pro.SEL)
    }
    status = "ok" if p is not None else "no_pinnacle" if books else "no_odds"
    note = (
        "Ninguna casa publica cuotas todavía para este partido; ESPN tampoco tiene precios disponibles."
        if status == "no_odds"
        else "Sin Pinnacle no hay valor medible; son precios ofrecidos."
        if p is None
        else "Pinnacle sin margen es la referencia; comparar precios no equivale a recomendar una apuesta."
    )
    selections = []
    lines = []
    labels = {"H": f"Gana {match[0]}", "D": "Empate", "A": f"Gana {match[1]}"}
    for i, s in enumerate(pro.SEL):
        if s not in best:
            continue
        price, book = best[s]
        fair = None if p is None else round(float(1 / p[i]), 3)
        edge = None if p is None else float(price * p[i] - 1)
        selections.append(
            {
                "selection": s,
                "label": labels[s],
                "best_odds": price,
                "bookmaker": book,
                "pinnacle_fair_odds": fair,
                "edge": edge,
            }
        )
        text = f"{labels[s]}: mejor {price:.3f} en {book}"
        if p is not None:
            text += f" · Pinnacle justo {fair:.3f} · ventaja {edge * 100:+.1f} %"
        lines.append(text)
    text = "\n".join([*lines, note])
    return {
        "match_id": match_id,
        "home": match[0],
        "away": match[1],
        **local_fields(match[2]),
        "status": status,
        "note": note,
        "selections": selections,
        "overround": margins,
        "has_pinnacle": p is not None,
        "comparison_text": text,
        "books": books,
    }
