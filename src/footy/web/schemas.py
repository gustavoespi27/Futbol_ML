"""Esquemas Pydantic de las respuestas de la API: el contrato que consumen app.js, combos.js y suggestions.js.

Los esquemas son estrictos (extra="forbid"): si el backend agrega o renombra un campo sin actualizar aquí, la
respuesta falla de forma visible en vez de cambiar en silencio lo que recibe el frontend. Las rutas usan
response_model_exclude_unset=True, así que un campo opcional que el backend no envía sigue sin aparecer en el JSON
(no se convierte en null): el contrato con el frontend queda idéntico.
"""

from pydantic import BaseModel, ConfigDict, Field

Prob3 = list[float]                              # [local, empate, visita]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --- /api/league-catalog -------------------------------------------------------------

class LeagueCatalogItem(Schema):
    code: str
    name: str
    country: str = Field(description="País en español ('Copas UEFA', 'Selecciones'... para torneos)")
    continent: str
    type: str = Field(description="league | cup | international")
    n: int = Field(description="Partidos en el horizonte del dashboard (hoy, mañana y pasado mañana)")
    model: bool = Field(description="Tiene modelo validado: se puede usar en el simulador")


# --- /api/tracking -------------------------------------------------------------------

class TrackingSummary(Schema):
    """Resumen del seguimiento prospectivo. Las métricas solo aparecen cuando hay partidos o apuestas evaluadas."""
    evaluated: int
    pending: int
    paper_bets: int
    hit_rate: float | None = None
    ll_official: float | None = None
    ll_model: float | None = None
    ll_market: float | None = None
    n_market: int | None = None
    ll_official_same: float | None = None
    bets_profit: float | None = None
    bets_yield: float | None = None
    bets_clv: float | None = None


class TrackedMatch(Schema):
    kickoff: str
    league: str
    league_name: str | None
    home: str
    away: str
    home_id: int | None
    away_id: int | None
    score: str
    y: int = Field(description="Resultado: 0 local, 1 empate, 2 visita")
    pick: int = Field(description="Resultado más probable según el sistema (0/1/2)")
    hit: bool
    p_official: Prob3 | None
    p_market: Prob3 | None
    version: str
    close_kind: str | None


class TrackedBet(Schema):
    kickoff: str
    partido: str
    league: str
    book: str
    sel: str
    odds: float
    ev: float | None
    won: bool
    profit: float | None
    clv: float | None
    version: str


class TrackingOverview(Schema):
    summary: TrackingSummary
    matches: list[TrackedMatch]
    bets: list[TrackedBet]


# --- /api/overview -------------------------------------------------------------------

class OverUnderSummary(Schema):
    n: int
    over_rate: float | None
    acc_model: float | None
    acc_official: float | None
    acc_market: float | None
    ll_model: float | None
    ll_official: float | None
    ll_market: float | None


class BacktestSummary(Schema):
    """Evaluación fuera de muestra de la temporada 2026."""
    n: int
    leagues: int
    from_: str = Field(alias="from")
    to: str
    acc_model: float
    acc_market: float
    acc_official: float
    ll_model: float
    ll_market: float
    ll_official: float
    acc_naive_home: float
    ou: OverUnderSummary


class ConfidenceBin(Schema):
    range: str
    n: int
    pred: float | None
    hit: float | None


class Engine(Schema):
    """Parámetros vigentes del motor: modelo ML, recalibración y reglas del apostador profesional."""
    ml_model: str | None = Field(description="poisson_goals: goles esperados λ (local) y μ (visita)")
    rho: float | None = Field(description="Corrección Dixon-Coles de la matriz de marcadores")
    n_competitions: int
    temperature: float = Field(description="Recalibración automática: T > 1 suaviza, T < 1 agudiza")
    sharp: str
    min_edge: float
    max_odds: float
    kelly_fraction: float
    max_stake: float
    max_daily: float


class Overview(Schema):
    backtest: BacktestSummary
    confidence: list[ConfidenceBin]
    tracking: TrackingSummary
    last_api_request: str | None
    last_daily_run: str | None
    n_leagues_model: int
    model_version: str
    engine: Engine


# --- /api/upcoming -------------------------------------------------------------------

class Verdict(Schema):
    level: str = Field(description="green | yellow | red | none")
    label: str
    reason: str


class MatchOption(Schema):
    """Una selección del partido con su probabilidad, cuota y semáforo."""
    key: str
    label: str
    group: str
    p: float
    fair: float | None
    odds: float | None
    book: str | None
    estimated: bool
    ev: float | None
    verdict: Verdict
    p_fair: float | None = Field(None, description="Solo 1X2 con Pinnacle: probabilidad justa sin margen")


class OddsDrift(Schema):
    """Movimiento de la cuota de Pinnacle entre la primera y la última captura antes del partido."""
    from_: float = Field(alias="from")
    to: float
    pct: float = Field(description="to / from − 1 (negativo: el mercado se volcó hacia la selección)")
    n: int
    signal: str | None = Field(description="a_favor | en_contra | null (movimiento menor a 3%)")


class ProBet(Schema):
    """Oportunidad 1X2 del apostador profesional: precio justo de Pinnacle y la mejor cuota entre casas."""
    key: str
    sel: str
    p_fair: float
    fair_odds: float
    pinnacle: float
    odds: float
    book: str
    edge: float
    bet: bool
    stake: float
    growth: float
    risk: str
    drift: OddsDrift | None = None


class Recommendation(Schema):
    bet: bool
    text: str
    sel: int | None = None
    book: str | None = None
    odds: float | None = None
    ev: float | None = None


class Variant(Schema):
    keys: list[str]
    label: str
    p: float
    fair: float | None


class Form(Schema):
    form_h: float | None
    form_a: float | None
    gf_h: float | None
    ga_h: float | None
    gf_a: float | None
    ga_a: float | None
    h2h_n: float | None
    h2h_pts: float | None


class MatchSummary(Schema):
    """Un partido próximo. Los campos de probabilidades faltan si la liga no tiene modelo ni cuotas, y en un
    partido que no se pudo calcular llegan `source: "error"` y `error`."""
    ref: str
    league: str
    league_name: str
    home: str
    away: str
    kickoff: str | None
    source: str
    options: list[MatchOption]
    suggestions: list[Variant]
    recommendation: Recommendation
    data_through: str | None
    stale: bool
    market_book: str | None = None
    home_id: int | None = None
    away_id: int | None = None
    p_official: Prob3 | None = None
    p_model: Prob3 | None = None
    p_market: Prob3 | None = None
    model_name: str | None = None
    form: Form | None = None
    xg: list[float | None] | None = None
    pro: list[ProBet] | None = None
    has_sharp: bool | None = None
    over25: float | None = None
    btts: float | None = None
    top_scores: list[tuple[str, float | None]] | None = None
    odds_1x2: dict[str, list[float]] | None = None
    error: str | None = None
    recent: dict[str, list[str]] | None = Field(
        None, description="Últimos 5 resultados de cada equipo (W/D/L, del más antiguo al más reciente)")
