# A3 — Modelo de selecciones absolutas

Evaluación del 2026-11-09. Implementación aprobada por Gustavo como excepción de solo lectura del motor.
No modifica `tracking.py` ni incorpora selecciones a apuestas en papel o pronósticos prospectivos.

## Datos y alcance

Fuente: [martj42/international_results](https://github.com/martj42/international_results), licencia CC0-1.0.
El CSV descargado contiene **49.940 partidos**, hasta **2026-10-06**. Se conserva en
`data/raw/international/results.csv`; ETag/Last-Modified y comprobación cada 24 horas evitan descargas repetidas.
Si falla la red, se conserva el archivo existente. La web solo lee el artefacto calculado; no descarga ni ajusta modelos.

El catálogo y los alias resuelven los **208 nombres de selecciones** encontrados en la DB. Se excluyen
**159 nombres**: categorías juveniles/sub-23 y cinco clubes mal clasificados como internacionales
(Alanyaspor, Albirex Niigata S, Hull, Johor Darul Takzim FC y Torpedo Zhodino).
La fixture de CI contiene los 367 nombres auditados; `prepare()` vuelve a auditar la base real y falla si aparece
una selección absoluta sin alias. No modifica ni fusiona equipos en SQLite.

Se complementa el CSV con resultados propios posteriores a su último día. Se deduplican nombres canónicos,
marcadores y fechas cercanas para resolver el cambio entre fecha local del CSV y UTC de la DB. En esta ejecución
no hubo resultados adicionales: el último encuentro en UTC de la DB ya estaba en el CSV con fecha local anterior.

## Modelo y temporalidad

Elo inicial de 1.500 puntos; expectativa `1 / (1 + 10 ** (-d / 400))`.
Localía de 100 puntos cuando está confirmada; cero en cancha neutral. El multiplicador de goles es el mismo
del Elo existente: 1 hasta un gol, 1,5 con dos y `(11 + diferencia) / 8` para tres o más.

| Torneo | K |
|---|---:|
| Amistoso | 20 |
| Otros | 30 |
| Eliminatorias y Nations League | 40 |
| Finales continentales | 50 |
| Mundial | 60 |

La conversión a goles es `λ = exp(a + b × d/400)` y `μ = exp(a − b × d/400)`, con límites numéricos
en la diferencia y las intensidades. Se ajustan únicamente `a` y `b` por verosimilitud Poisson en 2000–2021.
Parámetros finales: `a = 0,1906525904`, `b = 0,7746981980`. Las probabilidades proceden de
`markets/scoreline`, sin combinaciones opacas con el modelo de clubes.

Cada resultado tiene una fecha de disponibilidad:

- CSV sin hora/zona: **dos días UTC después** de su fecha. No se ven los resultados del mismo día ni del anterior.
- Resultados posteriores de la DB: kickoff UTC más tres horas.
- La consulta de rating incluye solo actualizaciones **estrictamente anteriores al kickoff**.
- Los parámetros se congelan antes de 2022: se excluyen tres partidos de fin de 2021 cuya disponibilidad
  conservadora cae en 2022. Quedan **20.808 partidos de ajuste**.
- Durante 2022–2026 se actualiza Elo con resultados que ya estaban disponibles, manteniendo fijos los parámetros Poisson.

El CSV identifica cancha neutral. La DB no conserva esa marca: en eliminatorias y fase regular UNL se usa localía;
en amistosos y finales sin sede verificable se omite la ventaja local. La ficha explica este supuesto.

## Walk-forward observado

Comando: `python scripts/eval_international.py --output reports/a3/evaluacion.json`.
El baseline trivial usa las frecuencias local/empate/visita del ajuste, sin información del conjunto de prueba.
La fila de ajuste es descriptiva dentro de muestra; la estimación fuera de muestra es 2022–2026.

| Periodo | Grupo | n | Log loss modelo | Log loss trivial | Acierto modelo |
|---|---|---:|---:|---:|---:|
| 2000–2021 | Todos | 20.808 | 0,8960 | 1,0488 | 58,65 % |
| 2000–2021 | Competitivos | 13.728 | 0,8553 | 1,0421 | 61,66 % |
| 2000–2021 | Amistosos | 7.080 | 0,9751 | 1,0617 | 52,80 % |
| 2022–2026 | Todos | **5.068** | **0,8768** | **1,0504** | **60,22 %** |
| 2022–2026 | Competitivos | 3.745 | 0,8670 | 1,0550 | 61,01 % |
| 2022–2026 | Amistosos | 1.323 | 0,9044 | 1,0376 | 57,97 % |

La referencia del prototipo recibido era 0,877 frente a 1,050 y 60,1 % en 5.068 partidos.
Las cifras de esta tabla fueron recalculadas, no copiadas. No se eligieron parámetros usando el resultado de prueba.

### Comparación emparejada contra Pinnacle

Se ejecutó la consulta de partidos internacionales terminados de 2022–2026 con tripleta completa H/D/A de
**Pinnacle**, de una misma fuente y captura, anterior o igual al kickoff. Se toma la última captura completa;
se excluyen capturas posteriores y no se sustituyen por Betfair u otra casa. Se elimina el margen proporcionalmente.
Las pruebas cubren capturas incompletas, posteriores y casas alternativas.

**Resultado real: n = 0.** Esta base no permite calcular log loss o acierto emparejado contra Pinnacle para selecciones.
Ambas métricas se devuelven como ausentes. La mejora frente al baseline trivial **no demuestra ventaja frente al
mercado ni rentabilidad**. La comparación queda implementada y se podrá medir al acumular cuotas internacionales
previas con resultado; no se fabrican cuotas históricas ni se afirma equivalencia con el mercado.

## Limitaciones del objetivo

El [README del dataset](https://github.com/martj42/international_results#content) especifica que sus marcadores
pueden incluir prórroga, sin tandas de penales. No ofrece marcador separado a 90 minutos. Por tanto, estas métricas
del CSV no son una validación estricta del mercado a 90 minutos. En la comparación emparejada se usa el resultado
de la DB, pero hoy no hay muestra con Pinnacle. El modelo es exploratorio y no habilita un registro prospectivo.

La disponibilidad diferida es conservadora y sacrifica información reciente. No existen regresión estacional,
lesiones, alineaciones ni ajustes por viajes. Los equipos con poco historial conservan mayor incertidumbre;
una probabilidad alta sigue sin demostrar una ventaja de precio.

## Integración y verificación

- El artefacto de aproximadamente **1,56 MiB** se calcula en la tarea diaria y se recarga por su versión de archivo.
  La firma del precálculo incorpora el modelo, el catálogo y los alias; no usa mtime del SQLite ni del WAL.
- Sin Pinnacle manda `modelo selecciones`; con Pinnacle manda su probabilidad sin margen y se conserva el modelo
  al lado. Una cuota de otra casa no sustituye esa referencia.
- El agente expone `probability_source`, `model_name`, cobertura Pinnacle y `value_status`.
- Los filtros de `register_suggestions` y `register_reliable` excluyen competiciones internacionales, incluso cuando
  la fuente oficial es mercado. No entran a `pro_bets`, `daily_picks` ni al seguimiento del modelo de clubes.
- En datos reales, **33 de 36 próximos partidos** quedaron con fuente `modelo selecciones`; los otros tres
  conservan sus fuentes previas. La lectura fría con regeneración del artefacto tardó 6,49 s en esta jornada;
  no equivale a un benchmark de arranque completo.
- 43 pruebas de A3: **100 %** de cobertura en ingest/modelo internacional. Suite completa de **312 tests**, Ruff, JavaScript y
  auditoría de ficha a 360/390/768/1440 px en ambos temas; sin desbordamientos, fallos de contraste detectados ni
  errores JS. Las capturas finales se incorporan en el paso 11.

Se actualizó únicamente el mapa de arquitectura de `CLAUDE.md` §3; ese archivo local sigue sin versionarse.
