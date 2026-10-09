# Seguimiento prospectivo (elo_dc_v3)

*Actualizado 2026-10-09 06:14 UTC por `scripts/daily.py`. Predicciones registradas antes de cada partido; sin dinero real.*

Partidos evaluados: **3** · pendientes de resultado: **50** · apuestas en papel: **2**

Ligas marcadas en el análisis 03: T1, I1, P1, SWE.

## Calidad probabilística (log loss; menor es mejor)

Mercado de referencia: cuotas de cierre sin margen; si aún no llegan, el último snapshot pre-partido.

| Versión | Grupo | Partidos | Acierto | Modelo | Modelo + mercado pre-partido | Mercado (referencia) |
|---|---|---:|---:|---:|---:|---:|
| elo_dc_v1 | Todas | 3 | 33% | 1.0288 | 1.0406 | 1.0338 (3) |

## Apuestas en papel

CLV = cuota tomada × probabilidad justa al cierre − 1. CLV medio positivo y sostenido es la señal más rápida de ventaja real; el yield necesita miles de apuestas para ser concluyente.

| Grupo | Apuestas | Acierto | Yield | CLV medio | % con CLV > 0 |
|---|---:|---:|---:|---:|---:|
| Todas | 2 | 0.0% | -100.0% | +4.68% | 100% |