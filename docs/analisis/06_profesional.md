# Análisis 06 — El apostador profesional (value betting contra Pinnacle)

*Generado por `scripts/pro_backtest.py`.*

109.263 partidos de 22 ligas europeas (football-data.co.uk). Cuotas **tempranas** (días antes del partido): precio justo = Pinnacle sin margen; se apuesta a la mejor cuota entre Bet365, BetWin, William Hill y 1xBet cuando la supera en ≥ 6% (cuota ≤ 4.0), una por partido, ¼ de Kelly con tope de 2% y 10% diario. CLV contra Pinnacle al cierre. Sin Pinnacle no se apuesta (football-data dejó de publicarlo en 2025-26).

Regla elegida con 2013-2021 entre 20 combinaciones de umbral y cuota máxima (la de mejor rendimiento con ≥ 300 apuestas); por eso el rendimiento de selección está inflado. La prueba es 2022 en adelante.

| Período | Apuestas | Acierto | Cuota media | Rendimiento [IC95%] | CLV medio | Con CLV > 0 |
|---|---:|---:|---:|---|---:|---:|
| Selección 2013-2021 | 419 | 42.0% | 3.25 | +30.0% [+14.7%; +45.3%] | +6.8% | 76% |
| Prueba 2022-2026 | 213 | 33.8% | 3.22 | +2.9% [-17.1%; +22.9%] | +5.3% | 77% |

## Por temporada

| Temporada | Apuestas | Acierto | Cuota media | Rendimiento [IC95%] | CLV medio | Con CLV > 0 |
|---|---:|---:|---:|---|---:|---:|
| 2012 | 34 | 52.9% | 3.37 | +85.9% [+24.5%; +147.3%] | +5.6% | 79% |
| 2013 | 21 | 47.6% | 2.94 | +28.6% [-34.0%; +91.1%] | +13.1% | 73% |
| 2014 | 19 | 36.8% | 3.55 | +23.7% [-53.3%; +100.7%] | +7.9% | 77% |
| 2015 | 26 | 42.3% | 3.57 | +48.6% [-21.6%; +118.9%] | +9.0% | 88% |
| 2016 | 23 | 43.5% | 3.28 | +33.9% [-32.7%; +100.5%] | +6.6% | 78% |
| 2017 | 25 | 28.0% | 3.43 | -15.0% [-71.9%; +41.9%] | +3.1% | 56% |
| 2018 | 56 | 37.5% | 3.63 | +36.8% [-10.1%; +83.6%] | +5.1% | 84% |
| 2019 | 73 | 35.6% | 3.37 | +14.2% [-22.4%; +50.8%] | +6.9% | 74% |
| 2020 | 67 | 40.3% | 3.19 | +22.5% [-15.0%; +60.0%] | +2.4% | 66% |
| 2021 | 109 | 52.3% | 2.90 | +48.2% [+20.0%; +76.3%] | +10.0% | 81% |
| 2022 | 38 | 44.7% | 2.75 | +12.3% [-29.9%; +54.5%] | +8.3% | 82% |
| 2023 | 47 | 27.7% | 3.35 | -13.3% [-55.5%; +28.9%] | +5.5% | 81% |
| 2024 | 112 | 33.9% | 3.35 | +9.7% [-19.1%; +38.6%] | +4.8% | 79% |
| 2025 | 16 | 25.0% | 3.10 | -20.0% [-90.7%; +50.7%] | +1.4% | 50% |

## Lectura

- **CLV positivo y sostenido** mientras hubo referencia de Pinnacle: la mayoría de las apuestas consiguió mejor precio que el cierre. Es la huella de una ventaja real (las casas blandas corrigen hacia Pinnacle).
- El rendimiento en dinero es ruidoso: con cuotas medias ~3 hacen falta miles de apuestas para separarlo del azar. El CLV converge mucho antes y es el indicador a seguir.
- Riesgos reales que el histórico no ve: las casas limitan o cierran cuentas ganadoras, las cuotas tempranas tienen límites de apuesta bajos y la cuota puede cambiar antes de que se coloque la apuesta.
