# Seguimiento prospectivo (elo_dc_v3)

*Actualizado 2026-10-09 16:58 UTC por `scripts/daily.py`. Predicciones registradas antes de cada partido; sin dinero real.*

Partidos evaluados: **8** · pendientes de resultado: **317** · apuestas en papel: **3**

Ligas marcadas en el análisis 03: T1, I1, P1, SWE.

## Calidad probabilística (log loss; menor es mejor)

Mercado de referencia: cuotas de cierre sin margen; si aún no llegan, el último snapshot pre-partido.

| Versión | Grupo | Partidos | Acierto | Modelo | Modelo + mercado pre-partido | Mercado (referencia) |
|---|---|---:|---:|---:|---:|---:|
| elo_dc_v1 | Todas | 8 | 50% | 1.0221 | 0.9259 | 0.9062 (8) |

## Apuestas en papel

CLV = cuota tomada × probabilidad justa al cierre − 1. CLV medio positivo y sostenido es la señal más rápida de ventaja real; el yield necesita miles de apuestas para ser concluyente.

| Grupo | Apuestas | Acierto | Yield | CLV medio | % con CLV > 0 |
|---|---:|---:|---:|---:|---:|
| Todas | 3 | 0.0% | -100.0% | +6.08% | 100% |