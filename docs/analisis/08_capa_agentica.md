# Evaluación reproducible de la capa agéntica

Ficha sintética fija; 15 preguntas por modelo; inferencia local real. Una ejecución por pregunta. La primera consulta incluye carga del modelo. Tokens/s = tokens de salida / latencia total (incluye prompt y herramientas); no es velocidad pura de generación. Memoria según /api/ps, no RAM total del sistema. La verificación numérica no valida la semántica ni la pertinencia.

## qwen2.5:7b

Memoria del modelo: 4535 MB; VRAM: 4535 MB.

| Pregunta | Esperada | Usadas | Argumentos válidos | Cifras verificadas | Segundos | Tokens/s |
|---|---|---|---|---|---:|---:|
| ¿Qué partidos hay en los próximos días? | get_upcoming_matches | get_upcoming_matches | True | True | 10.157 | 10.93 |
| ¿Cuándo juega Arsenal su próximo partido? | get_upcoming_matches | get_upcoming_matches | True | False | 7.038 | 17.19 |
| Dame los próximos 2 partidos de la liga E0. | get_upcoming_matches | get_upcoming_matches | True | True | 6.783 | 16.22 |
| ¿Qué apuestas con valor frente a Pinnacle hay? | get_value_bets | get_value_bets | False | True | 5.378 | 9.48 |
| Busca oportunidades con ventaja mínima de 8%. | get_value_bets | get_value_bets | True | True | 6.132 | 13.7 |
| ¿Hay alguna apuesta con ventaja superior a 10%? | get_value_bets | get_value_bets | True | False | 5.466 | 9.51 |
| Simula Arsenal contra Everton en E0. | simulate_match | simulate_match | True | True | 7.151 | 16.36 |
| ¿Cuántos goles esperados tiene Arsenal contra Everton en E0? | simulate_match | simulate_match | True | True | 5.922 | 12.49 |
| Simula Everton como local frente a Arsenal en la liga E0. | simulate_match | simulate_match | True | True | 6.623 | 16.16 |
| ¿Cómo va la tabla de la liga E0? | get_league_standings | get_league_standings | True | True | 5.875 | 11.92 |
| ¿Quién lidera la liga E0? | get_league_standings | get_league_standings | True | True | 5.239 | 8.21 |
| Muéstrame los puntos y la racha de Arsenal en la tabla E0. | get_league_standings | get_league_standings | False | True | 6.176 | 13.6 |
| ¿Cómo está rindiendo el sistema? | get_system_performance | get_system_performance | True | True | 6.497 | 14.78 |
| ¿Cuál es el CLV del sistema? | get_system_performance | get_system_performance | True | True | 5.001 | 7.2 |
| ¿Cuántos partidos evaluados y qué yield tiene el seguimiento? | get_system_performance | get_system_performance | True | True | 5.926 | 12.32 |
## qwen2.5:3b

Memoria del modelo: 2063 MB; VRAM: 2063 MB.

| Pregunta | Esperada | Usadas | Argumentos válidos | Cifras verificadas | Segundos | Tokens/s |
|---|---|---|---|---|---:|---:|
| ¿Qué partidos hay en los próximos días? | get_upcoming_matches | get_upcoming_matches | True | True | 8.356 | 17.71 |
| ¿Cuándo juega Arsenal su próximo partido? | get_upcoming_matches | get_upcoming_matches | True | True | 5.114 | 14.47 |
| Dame los próximos 2 partidos de la liga E0. | get_upcoming_matches | get_upcoming_matches | True | True | 5.248 | 14.29 |
| ¿Qué apuestas con valor frente a Pinnacle hay? | get_value_bets | get_value_bets | False | False | 5.296 | 14.35 |
| Busca oportunidades con ventaja mínima de 8%. | get_value_bets | get_value_bets | True | False | 5.059 | 12.85 |
| ¿Hay alguna apuesta con ventaja superior a 10%? | get_value_bets | get_value_bets | False | False | 4.796 | 8.97 |
| Simula Arsenal contra Everton en E0. | simulate_match | simulate_match | True | True | 5.545 | 19.66 |
| ¿Cuántos goles esperados tiene Arsenal contra Everton en E0? | simulate_match | simulate_match | True | True | 5.523 | 21.0 |
| Simula Everton como local frente a Arsenal en la liga E0. | simulate_match | simulate_match | True | False | 5.459 | 19.24 |
| ¿Cómo va la tabla de la liga E0? | get_league_standings | get_league_standings | True | True | 4.929 | 12.58 |
| ¿Quién lidera la liga E0? | get_league_standings | get_league_standings | True | True | 4.954 | 11.71 |
| Muéstrame los puntos y la racha de Arsenal en la tabla E0. | get_league_standings | get_league_standings | True | True | 4.98 | 12.05 |
| ¿Cómo está rindiendo el sistema? | get_system_performance | get_system_performance | True | True | 5.165 | 14.33 |
| ¿Cuál es el CLV del sistema? | get_system_performance | get_system_performance | True | True | 4.73 | 7.82 |
| ¿Cuántos partidos evaluados y qué yield tiene el seguimiento? | get_system_performance | get_system_performance | True | True | 4.8 | 9.37 |
