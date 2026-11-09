"""Genera el análisis descriptivo de CLV por referencia, sin modificar el motor."""

from contextlib import closing

from footy import config
from footy.db.connection import connect
from footy_agents.analytics.clv import markdown, settled_bets, summarize


def main() -> None:
    with closing(connect()) as conn:
        report = markdown(summarize(settled_bets(conn)))
    path = config.PROJECT_ROOT / "docs/analisis/07_clv_referencia.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
