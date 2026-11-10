"""Continuidad e intención deterministas; no calcula pronósticos ni ejecuta herramientas."""

import re

from footy_agents.calendar import calendar_args
from footy_agents.names import normalize_name
from footy_agents.tools import NICKNAMES, league_in_text, service, upcoming_focus

# Cruce hipotético entre dos equipos: «¿quién ganaría Colo Colo contra el Barcelona?», «simula A vs B».
MATCHUP = re.compile(r"(?:quien ganaria|ganaria|simula(?:r|cion)?(?: de)?|si jugaran|que pasa(?:ria)? si juega[n]?|"
                     r"si juega[n]?|como saldria|como seria|(?:si |que )?se enfrent(?:a|an|ara|aran|ase|asen|e|en)|"
                     r"enfrentamiento(?: entre)?|"
                     r"hipotetico(?: caso)?(?: de)?(?: que)?(?: se enfrent(?:a|an|e|en)| jueguen?| juega[n]?)?)\s+"
                     r"(?:un partido entre |el partido |entre )?(.+?)\s+(?:contra|vs|versus|frente a|y)\s+(.+)$")
# Lo que sigue al segundo equipo es la pregunta, no el nombre: «… vs barcelona, ¿cuáles son los porcentajes?».
TAIL = re.compile(r"[,?]|\s(?:cuales?|quien|que|como|cuanto|con que|porcentajes?|probabilidad)\b.*$")
# «Colo Colo vs Barcelona» a secas: solo frases cortas, para no confundir preguntas largas con un cruce.
BARE_MATCHUP = re.compile(r"^(.+?)\s+(?:contra|vs|versus)\s+(.+)$")
ARTICLE = re.compile(r"^(?:el|la|los|las|al|a)\s+")
ACTION_WORDS = {"analiza", "partido", "pronostico", "cuotas", "cuota", "como", "que", "quien", "tabla", "forma",
                "llega", "juega", "juegan", "jugo", "fue", "paga", "compara", "dame", "muestra"}


def matchup(q: str) -> tuple[str, str] | None:
    m = MATCHUP.search(q)
    bare = None if m else BARE_MATCHUP.search(q)
    if bare and any(len(side.split()) > 3 or set(side.split()) & ACTION_WORDS for side in bare.groups()):
        bare = None
    m = m or bare
    if not m:
        return None
    home, away = (ARTICLE.sub("", TAIL.split(side, maxsplit=1)[0]).strip() for side in m.groups())
    return (home, away) if home and away else None


def _scheduled(home: str, away: str) -> int | None:
    """Si el cruce está en el calendario, se analiza el partido real en vez de simularlo."""
    def norm(name: str) -> str:
        return normalize_name(NICKNAMES.get(normalize_name(name), name))
    pair = {norm(home), norm(away)}
    for m in service.upcoming():
        if {normalize_name(m["home"]), normalize_name(m["away"])} == pair:
            return int(str(m["ref"]).removeprefix("m:")) if m.get("ref") else None
    return None


ODDS_INTENT = re.compile(r"\b(?:cuanto paga|cuotas?|compara cuotas|que casa paga mas)\b")


# Preguntas cortas sobre una tabla ya mostrada («¿y los últimos?»): continúan solo si hay una liga en el contexto.
TABLE_FOLLOW = r"\b(?:tabla|ultimos|primeros|descenso|lider|puntero|colista)\b"


def is_follow_up(message: str, entities: dict | None) -> bool:
    """Solo referencias cortas sin un equipo o liga distintos conservan memoria."""
    q = normalize_name(message).lstrip("¿¡ ")
    if len(message.strip()) >= 80 or not (
        re.match(r"^(?:y|si|dale|ok)\b", q) or any(re.search(r"\b" + phrase + r"\b", q)
                                 for phrase in ("ese partido", "este partido", "el mismo", "ahi", "favorito",
                                                "y manana", "eso", "esa", "ese", "otro", "otra",
                                                "otros", "otras", "mas", "esos", "esas", "estos", "estas",
                                                "el primero", "el segundo", "la primera", "de la lista",
                                                "compara cuotas", "cuanto paga", "que casa paga mas",
                                                "cuota", "cuotas"))
        or ((entities or {}).get("league") and re.search(TABLE_FOLLOW, q))
    ):
        return False
    entities = entities or {}
    known = {normalize_name(str(entities[k])) for k in ("home", "away", "team", "league", "league_name")
             if entities.get(k)}
    mentions: set[str] = set()
    for alias, canonical in NICKNAMES.items():
        if f" {alias} " in f" {q} ":
            mentions.add(normalize_name(canonical))
    try:
        focus = upcoming_focus(message)
        if focus:
            mentions.update(normalize_name(str(focus[k])) for k in ("team", "league") if focus.get(k))
        for league in service.league_catalog():
            for key in ("code", "name"):
                if f" {normalize_name(league[key])} " in f" {q} ":
                    if not {normalize_name(league['code']), normalize_name(league['name'])} & known:
                        return False
        matches = service.upcoming()
        for match in matches:
            id_ = match.get("match_id") or str(match.get("ref", "")).removeprefix("m:")
            if str(id_) in {str(i) for i in entities.get("shown_ids", [])}:
                known.update(normalize_name(str(match[k])) for k in ("home", "away", "league", "league_name")
                             if match.get(k))
        for match in matches:
            for side in ("home", "away"):
                name = normalize_name(match[side])
                if f" {name} " in f" {q} ":
                    mentions.add(name)
    except (KeyError, ValueError, OSError, RuntimeError):
        return False  # si no se puede comprobar la identidad, evitar arrastrar otro tema
    return not (mentions - known)


def intent_route(message: str, entities: dict | None = None) -> tuple[str, dict] | None:
    """Una herramienta por intención original; los argumentos desconocidos no se inventan."""
    q = normalize_name(message)
    for pattern, tool in ((r"deja de vigilar|cancela.*vigilan", "cancel_watch"),
                          (r"que vigilas|mis alertas|lista.*vigilan|mis vigilan", "list_watches"),
                          (r"agrega.*favoritos|anade.*favoritos", "add_favorite"),
                          (r"avisame|vigila|alerta", "create_watch")):
        if re.search(pattern, q):
            args: dict = {}
            if tool == "cancel_watch":
                id_ = re.search(r"\b\d+\b", q)
                if id_:
                    args["id"] = int(id_[0])
            return tool, args
    # «Cuotas con valor» o «recomendaciones» son otra intención: no se comparan casas de un partido.
    teams = matchup(q)
    if teams:
        match_id = _scheduled(*teams)
        if match_id:
            return "analyze_match", {"match_id": match_id}
        return "simulate_match", {"home_team": teams[0], "away_team": teams[1]}
    if ODDS_INTENT.search(q) and not re.search(r"valor|ventaja|recomend|fiables?|semaforo", q):
        return "request_odds", {"match_id": entities["match_id"]} if entities and entities.get("match_id") else {}
    for pattern, tool in (
        (r"recomendacion|mas fiables?|casi con valor|cerca de tener valor|"
         r"secciones? de apuestas|donde (?:estan|veo|encuentro).*apuestas", "get_recommendations"),
        (r"rendimiento|fiable|fiabilidad|clv|yield|acierto", "get_system_performance"),
        (r"banca|cuanto.*apostar|pesos", "get_stake_limits"),
        (r"por que no hay|cobertura|actualizad", "get_coverage"),
        (r"valor|ventaja", "get_value_bets"),
        (r"como llega|forma|racha", "get_team_form"),
        (r"tabla|posicion|ultimos|descenso|colista|lider|puntero", "get_league_standings"),
        (r"simula", "simulate_match"),
        (r"partidos?.*(?:vienen|hay|juega)|calendario|(?:otros?|mas).*partidos?|"
         r"partidos.*(?:importantes?|destacad|grandes?)", "get_upcoming_matches"),
    ):
        if re.search(pattern, q):
            args: dict = {}
            if tool == "get_upcoming_matches":
                args = calendar_args(message, entities)
            if tool == "get_recommendations":
                section = ("casi_valor" if re.search(r"casi|cerca de tener", q) else
                           "fiables" if re.search(r"fiables?", q) else "todas")
                args = {"section": section}
            if tool == "get_stake_limits":
                number = re.search(r"\d[\d.,]*", message)
                if number:
                    raw = number[0]
                    raw = re.sub(r"[.,](?=\d{3}(?:\D|$))", "", raw)
                    args = {"bankroll": float(raw.replace(",", "."))}
            elif tool == "get_team_form" and entities and entities.get("team"):
                args = {"team": entities["team"]}
            elif tool == "get_league_standings":
                league = league_in_text(message) or (entities or {}).get("league")
                part = ("bottom" if re.search(r"ultimos|descenso|colista|zona baja|abajo|peores|cola", q) else
                        "all" if re.search(r"completa|toda la tabla|todos los equipos", q) else "top")
                args = {"league": league, **({"part": part} if part != "top" else {})} if league else {}
            return tool, args
    if entities and entities.get("shown_ids") and re.match(r"^(?:si|dale|ok|otros?|otras?|mas)\b", q):
        return "get_upcoming_matches", calendar_args(message, entities)
    if entities and entities.get("match_id"):
        return "analyze_match", {"match_id": entities["match_id"]}
    if "analiza" in q or "pronost" in q or re.search(r"probab.*partido", q):
        return "analyze_match", {}
    return None
