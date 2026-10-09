-- Esquema SQLite de Futbol_ML.
-- Convención: todas las fechas/horas en ISO-8601 UTC ('YYYY-MM-DDTHH:MM:SSZ').
-- Anti-leakage: cada dato observacional guarda cuándo lo conocimos
-- (captured_at / reported_at). Las features solo pueden usar filas con
-- marca de tiempo anterior al momento de predicción.

CREATE TABLE IF NOT EXISTS competitions (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,      -- CHL, ARG, BRA, LIB, ...
    name        TEXT NOT NULL,
    country     TEXT,
    type        TEXT NOT NULL              -- league | cup
);

CREATE TABLE IF NOT EXISTS teams (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,             -- nombre canónico
    country     TEXT,
    UNIQUE (name, country)
);

-- Cada fuente nombra/identifica a los equipos a su manera.
CREATE TABLE IF NOT EXISTS team_aliases (
    source      TEXT NOT NULL,             -- football_data | api_football
    alias       TEXT NOT NULL,             -- nombre o id externo
    team_id     INTEGER NOT NULL REFERENCES teams(id),
    PRIMARY KEY (source, alias)
);

CREATE TABLE IF NOT EXISTS matches (
    id              INTEGER PRIMARY KEY,
    competition_id  INTEGER NOT NULL REFERENCES competitions(id),
    season          TEXT NOT NULL,
    round           TEXT,
    kickoff_utc     TEXT NOT NULL,
    home_team_id    INTEGER NOT NULL REFERENCES teams(id),
    away_team_id    INTEGER NOT NULL REFERENCES teams(id),
    status          TEXT NOT NULL,         -- scheduled | live | finished | postponed | cancelled
    home_goals      INTEGER,               -- resultado a los 90'
    away_goals      INTEGER,
    venue           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_matches_kickoff ON matches (kickoff_utc);
CREATE INDEX IF NOT EXISTS ix_matches_teams ON matches (home_team_id, away_team_id);

-- Identificadores externos de cada partido (un partido puede venir de varias fuentes).
CREATE TABLE IF NOT EXISTS match_sources (
    source              TEXT NOT NULL,
    source_match_id     TEXT NOT NULL,
    match_id            INTEGER NOT NULL REFERENCES matches(id),
    details_fetched_at  TEXT,              -- alineaciones/estadísticas descargadas
    PRIMARY KEY (source, source_match_id)
);
CREATE INDEX IF NOT EXISTS ix_match_sources_match ON match_sources (match_id);

CREATE TABLE IF NOT EXISTS odds (
    id          INTEGER PRIMARY KEY,
    match_id    INTEGER NOT NULL REFERENCES matches(id),
    source      TEXT NOT NULL,
    bookmaker   TEXT NOT NULL,
    market      TEXT NOT NULL,             -- 1X2 | OU | BTTS
    line        REAL NOT NULL DEFAULT 0,   -- 2.5 para OU; 0 si no aplica
    selection   TEXT NOT NULL,             -- H/D/A | OVER/UNDER | YES/NO
    price       REAL NOT NULL CHECK (price > 1),
    captured_at TEXT NOT NULL,             -- cuándo vimos esta cuota
    is_closing  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (match_id, source, bookmaker, market, line, selection, captured_at)
);
CREATE INDEX IF NOT EXISTS ix_odds_match ON odds (match_id);

-- Formato largo: permite incorporar nuevas estadísticas sin migraciones.
CREATE TABLE IF NOT EXISTS team_match_stats (
    match_id    INTEGER NOT NULL REFERENCES matches(id),
    team_id     INTEGER NOT NULL REFERENCES teams(id),
    stat        TEXT NOT NULL,             -- shots_on_goal, expected_goals, ...
    value       REAL,
    source      TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (match_id, team_id, stat, source)
);

CREATE TABLE IF NOT EXISTS players (
    id                  INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    source              TEXT NOT NULL,
    source_player_id    TEXT NOT NULL,
    UNIQUE (source, source_player_id)
);

CREATE TABLE IF NOT EXISTS lineups (
    match_id    INTEGER NOT NULL REFERENCES matches(id),
    team_id     INTEGER NOT NULL REFERENCES teams(id),
    player_id   INTEGER NOT NULL REFERENCES players(id),
    is_starter  INTEGER NOT NULL,
    position    TEXT,
    grid        TEXT,
    formation   TEXT,
    source      TEXT NOT NULL,
    captured_at TEXT NOT NULL,             -- si es posterior al kickoff, NO es info pre-partido
    PRIMARY KEY (match_id, player_id, source)
);

CREATE TABLE IF NOT EXISTS player_match_stats (
    match_id    INTEGER NOT NULL REFERENCES matches(id),
    player_id   INTEGER NOT NULL REFERENCES players(id),
    team_id     INTEGER NOT NULL REFERENCES teams(id),
    stat        TEXT NOT NULL,             -- games_minutes, goals_total, ...
    value       REAL,
    source      TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (match_id, player_id, stat, source)
);

CREATE TABLE IF NOT EXISTS injuries (
    id          INTEGER PRIMARY KEY,
    match_id    INTEGER REFERENCES matches(id),
    team_id     INTEGER NOT NULL REFERENCES teams(id),
    player_id   INTEGER NOT NULL REFERENCES players(id),
    type        TEXT,
    reason      TEXT,
    source      TEXT NOT NULL,
    reported_at TEXT NOT NULL,
    UNIQUE (match_id, player_id, source)
);

CREATE TABLE IF NOT EXISTS predictions (
    id              INTEGER PRIMARY KEY,
    match_id        INTEGER NOT NULL REFERENCES matches(id),
    model_version   TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    p_home          REAL NOT NULL,
    p_draw          REAL NOT NULL,
    p_away          REAL NOT NULL,
    lambda_home     REAL,
    lambda_away     REAL,
    extra_json      TEXT
);
CREATE INDEX IF NOT EXISTS ix_predictions_match ON predictions (match_id);

CREATE TABLE IF NOT EXISTS api_requests (
    id              INTEGER PRIMARY KEY,
    source          TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    params          TEXT NOT NULL,
    requested_at    TEXT NOT NULL,
    http_status     INTEGER,
    results         INTEGER,
    errors          TEXT
);

-- Apuestas sugeridas (footy.betting.suggestions), registradas antes del partido para medir su resultado real.
-- Una fila por pierna; las de una doble comparten group_id.
CREATE TABLE IF NOT EXISTS suggestions (
    id              INTEGER PRIMARY KEY,
    created_at      TEXT NOT NULL,
    group_id        TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('simple', 'doble')),
    match_id        INTEGER NOT NULL REFERENCES matches(id),
    selection       TEXT NOT NULL,
    p               REAL NOT NULL,
    odds            REAL NOT NULL,
    book            TEXT,
    stake           REAL NOT NULL,
    model_version   TEXT NOT NULL,
    UNIQUE (group_id, match_id, selection)
);
CREATE INDEX IF NOT EXISTS ix_suggestions_match ON suggestions (match_id);
