"""Catálogo de competiciones: nombres, país y continente en español."""

from footy import config
from footy.ingest.football_data import leagues as fd_leagues


def league_names() -> dict[str, str]:
    cfg = fd_leagues()
    names = {c: v["name"] for c, v in {**cfg["main"], **cfg["extra"]}.items()}
    for code, c in config.settings()["competitions"].items():
        names.setdefault(code, c["name"])
    return names


COUNTRY_ES = {
    "England": "Inglaterra", "Scotland": "Escocia", "Germany": "Alemania", "Italy": "Italia", "Spain": "España",
    "France": "Francia", "Netherlands": "Países Bajos", "Belgium": "Bélgica", "Portugal": "Portugal",
    "Turkey": "Turquía", "Greece": "Grecia", "Austria": "Austria", "Denmark": "Dinamarca", "Finland": "Finlandia",
    "Ireland": "Irlanda", "Norway": "Noruega", "Poland": "Polonia", "Romania": "Rumania", "Russia": "Rusia",
    "Sweden": "Suecia", "Switzerland": "Suiza", "Argentina": "Argentina", "Brazil": "Brasil", "Chile": "Chile",
    "Mexico": "México", "USA": "Estados Unidos", "China": "China", "Japan": "Japón",
    "Europe": "Copas UEFA", "South America": "Copas CONMEBOL", "World": "Selecciones",
}
CONTINENT = {
    **dict.fromkeys(["England", "Scotland", "Germany", "Italy", "Spain", "France", "Netherlands", "Belgium",
                     "Portugal", "Turkey", "Greece", "Austria", "Denmark", "Finland", "Ireland", "Norway", "Poland",
                     "Romania", "Russia", "Sweden", "Switzerland", "Europe"], "Europa"),
    **dict.fromkeys(["Argentina", "Brazil", "Chile", "South America"], "Sudamérica"),
    **dict.fromkeys(["Mexico", "USA"], "Norteamérica"),
    **dict.fromkeys(["China", "Japan"], "Asia"),
    "World": "Selecciones",
}


def league_catalog(matches: list[dict]) -> list[dict]:
    """Todas las competiciones con país y continente (en español) y su cantidad de partidos en `matches`."""
    cfg, comps = fd_leagues(), config.settings()["competitions"]
    info = {c: {"country": v["country"], "type": "league"} for g in ("main", "extra") for c, v in cfg[g].items()}
    info.update({c: {"country": v.get("country"), "type": v["type"]} for c, v in comps.items()})
    counts: dict[str, int] = {}
    for m in matches:
        counts[m["league"]] = counts.get(m["league"], 0) + 1
    names = league_names()
    out = []
    for code, v in info.items():
        country = v["country"] or ""
        out.append({"code": code, "name": names.get(code, code), "country": COUNTRY_ES.get(country, country),
                    "continent": CONTINENT.get(country, "Otros"), "type": v["type"], "n": counts.get(code, 0)})
    return sorted(out, key=lambda r: (-r["n"], r["name"]))
