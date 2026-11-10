
## linea_base — 2026-11-09T00:49:41Z

Frío: proceso nuevo, con artefactos de disco existentes. RAM: working set del proceso de cálculo; no incluye Ollama, GPU ni el proceso web. Arranque: disponibilidad HTTP, no fin del prewarm. No equivale a un benchmark con datos actualizados.

```json
{
  "importacion_s": 1.5362406999993254,
  "upcoming": [
    {
      "muestra": "frio",
      "segundos": 0.0863,
      "ram_mb": 154.4,
      "partidos": 0
    },
    {
      "muestra": "caliente",
      "segundos": 0.0,
      "ram_mb": 154.4,
      "partidos": 0
    }
  ],
  "arranque_http_s": 2.217,
  "endpoints": [
    {
      "ruta": "/api/agent/chat",
      "segundos": 4.129,
      "primer_texto_s": 4.128550500001438,
      "caracteres": 165,
      "eventos": [
        "token",
        "done"
      ],
      "tokens_s": null,
      "nota": "SSE no publica tokens del proveedor; caracteres no son tokens."
    },
    {
      "ruta": "/api/agent/briefing",
      "segundos": 0.005,
      "primer_texto_s": 0.004903100001683924,
      "caracteres": 76,
      "eventos": [
        "token",
        "done"
      ],
      "tokens_s": null,
      "nota": "SSE no publica tokens del proveedor; caracteres no son tokens."
    }
  ]
}
```

## despues_L2_L3 — 2026-11-09T00:59:30Z

Frío: proceso nuevo, con artefactos de disco existentes. RAM: working set del proceso de cálculo; no incluye Ollama, GPU ni el proceso web. Arranque: disponibilidad HTTP, no fin del prewarm. No equivale a un benchmark con datos actualizados.

```json
{
  "importacion_s": 1.5519773999985773,
  "upcoming": [
    {
      "muestra": "frio",
      "segundos": 0.0817,
      "ram_mb": 155.34,
      "partidos": 0
    },
    {
      "muestra": "caliente",
      "segundos": 0.0007,
      "ram_mb": 155.34,
      "partidos": 0
    }
  ],
  "arranque_http_s": 2.224,
  "endpoints": []
}
```

## despues_L2_L3_con_Ollama — 2026-11-09T01:11:23Z

Frío: proceso nuevo, con artefactos de disco existentes. RAM: working set del proceso de cálculo; no incluye Ollama, GPU ni el proceso web. Arranque: disponibilidad HTTP, no fin del prewarm. No equivale a un benchmark con datos actualizados.

```json
{
  "importacion_s": 2.1691872000010335,
  "upcoming": [
    {
      "muestra": "frio",
      "segundos": 0.1073,
      "ram_mb": 154.78,
      "partidos": 0
    },
    {
      "muestra": "caliente",
      "segundos": 0.001,
      "ram_mb": 154.78,
      "partidos": 0
    }
  ],
  "arranque_http_s": 2.736,
  "endpoints": [
    {
      "ruta": "/api/agent/chat",
      "segundos": 14.249,
      "primer_texto_s": 12.822121599998354,
      "caracteres": 205,
      "eventos": [
        "tool_start",
        "tool_result",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "token",
        "done"
      ],
      "tokens_s": null,
      "nota": "SSE no publica tokens del proveedor; caracteres no son tokens."
    },
    {
      "ruta": "/api/agent/briefing",
      "segundos": 0.007,
      "primer_texto_s": 0.006903699999384116,
      "caracteres": 76,
      "eventos": [
        "token",
        "done"
      ],
      "tokens_s": null,
      "nota": "SSE no publica tokens del proveedor; caracteres no son tokens."
    }
  ]
}
```

## L3_revision_explicita_jornada_real — 2026-11-09T01:54:00Z

Frío: proceso nuevo, con artefactos de disco existentes. RAM: working set del proceso de cálculo; no incluye Ollama, GPU ni el proceso web. Arranque: disponibilidad HTTP, no fin del prewarm. No equivale a un benchmark con datos actualizados.

```json
{
  "importacion_s": 1.9921859999994922,
  "upcoming": [
    {
      "muestra": "frio",
      "segundos": 32.9354,
      "ram_mb": 378.27,
      "partidos": 17
    },
    {
      "muestra": "caliente",
      "segundos": 0.0909,
      "ram_mb": 384.24,
      "partidos": 17
    }
  ],
  "live_scores": {
    "base": "copia aislada de datos reales",
    "muestras": [
      {
        "lectura": "memoria",
        "segundos": 0.0008,
        "partidos": 17,
        "firma_estable": true
      },
      {
        "lectura": "memoria",
        "segundos": 0.0009,
        "partidos": 17,
        "firma_estable": true
      },
      {
        "lectura": "disco",
        "segundos": 0.0115,
        "partidos": 17,
        "firma_estable": true
      }
    ],
    "recalculos_tras_escrituras": 0,
    "nota": "Marcadores de prueba solo en copia"
  },
  "arranque_http_s": 2.738,
  "endpoints": []
}
```

## Correccion L3: revision explicita y jornada real

Comando: `python scripts/measure_footprint.py --live-check --label L3_revision_explicita_jornada_real`.

Jornada del 2026-11-08 (Chile), base recolectada desde ESPN: 17 partidos futuros en el horizonte de cinco dias. La prueba copia la base con SQLite backup y escribe tres marcadores de prueba solo en esa copia. Las dos primeras lecturas usan memoria; la tercera fuerza lectura de disco. No es una prueba de carga concurrente.

| Escenario | Tiempo | Recalculos por live_scores |
|---|---:|---:|
| Calculo inicial con 17 partidos | 32,9354 s | No aplica |
| Lectura en memoria despues de escritura 1 | 0,0008 s | 0 |
| Lectura en memoria despues de escritura 2 | 0,0009 s | 0 |
| Lectura desde disco despues de escritura 3 | 0,0115 s | 0 |

La firma permanece igual en las tres escrituras. RAM del proceso: 378,27 MiB en frio y 384,24 MiB en caliente. La segunda llamada de calentamiento tardo 0,0909 s; no se atribuye ese tiempo a una escritura live.

La firma usa revision explicita atomica publicada por daily.py y prekickoff.py al comenzar y finalizar sus ciclos, mas archivos de configuracion, modelos y calibracion. No lee mtime de football.sqlite ni del WAL. Cambios manuales de cuotas o partidos fuera de esas tareas requieren publicar una revision o forzar regeneracion. El vencimiento sigue limitado por edad y medianoche local; los partidos iniciados se filtran al leer. upcoming() no vacia _predictors ni _contexts. La prueba automatizada comprueba memoria, disco, cambio de revision, modelo y paso del kickoff sin recalculo global.

No hay una medicion anterior con esta misma jornada bajo el codigo antiguo; la comparacion anterior/despues de escrituras demuestra reutilizacion, no un porcentaje de ahorro global.

## B1 — Ollama bajo demanda (2026-11-09)

Experimento real en Windows, RTX 4060 8 GiB, Qwen 2.5 7B Q4_K_M; una respuesta corta y espera natural de cinco minutos. Comando: `python scripts/measure_footprint.py --runtime-cycle --output reports/agente/runtime-cycle.json`. Requiere Ollama apagado; rechaza detener una instancia externa y no sobrescribe Markdown.

| Estado | RAM servidor MiB | RAM Ollama y auxiliares MiB | VRAM modelo MiB | VRAM GPU total MiB |
|---|---:|---:|---:|---:|
| servidor_solo | 176.24 | 0.00 | 0.00 | 2995 |
| ollama_en_reposo | 176.24 | 57.65 | 0.00 | 3002 |
| modelo_cargado | 177.59 | 797.84 | 4535.10 | 7660 |
| despues_keep_alive | 187.54 | 59.10 | 0.00 | 3067 |

RAM: working set de los procesos, incluido el hijo real de Python y los auxiliares de Ollama; no se suma solo el lanzador de la venv. GPU total viene de `nvidia-smi` e incluye escritorio y otras aplicaciones; la columna del modelo viene de `/api/ps`. Tras el keep-alive, `/api/ps` devuelve una lista vacía y desaparece `llama-server`. La memoria del servidor puede crecer durante su calentamiento.

Al sumar se excluyeron los procesos Java 14864/28328: sus fechas de creación son anteriores al Python padre aparente (PID reutilizado por Windows). El script quedó corregido para exigir creación posterior al padre. La primera prueba descartada fue interrumpida para corregir el muestreo y no se usa en esta tabla.

Comportamiento: `agents.llm.autostart: true`, ejecutable configurable (`ollama` o ruta), inicio sin ventana en BELOW_NORMAL, `OLLAMA_KEEP_ALIVE=5m`, un modelo y una inferencia paralela. Health únicamente sondea. Expone `autostart` y `startup_failed`; la franja distingue reposo y fallo. El servidor conserva la propiedad del proceso que inició y no detiene una instancia previa.

Resumen: reserva persistida por usuario y fecha local de Chile antes de inferir, incluso si falla. Máximo un intento diario; cambios posteriores de datos o preferencias producen una plantilla actualizada. El día siguiente renueva el presupuesto. El modo plantilla no inicia Ollama.

Validación: 240 tests completos; 103 del agente, cobertura 96 %; Ruff, ocho tests web y `node --check app.js` en verde. Navegador: estados health controlados en 360/390/768/1440 px y ambos temas, sin desbordamiento ni fallos de contraste detectados. No es una medición de Lighthouse.

No se atribuye un porcentaje global de ahorro contra las mediciones antiguas: cambian la jornada y las condiciones. El ahorro demostrado aquí es liberar el modelo y su VRAM sin cerrar el panel.

## B2 — Automatización adaptativa (2026-11-09)

Benchmark reproducible: `python scripts/measure_automation.py`. Copia SQLite mediante backup, configuración, modelos y procesados a `reports/automation-<fecha>`; usa un proceso nuevo por caso y no modifica la base original. La primera ejecución no tiene revisión persistida; la segunda reutiliza exactamente la misma ingesta congelada. ESPN, API-Football, CSV y fixtures remotos están sustituidos por entradas sin cambios: no se gastan cuotas. Sí corren los modelos y el resto del pipeline local.

| Caso | Duración | CPU acumulada | Recalibración / entre ligas / ML |
|---|---:|---:|---|
| con_cambios | 61.014 s | 59.656 s | recalibrate: ejecutado; cross_league: ejecutado; ml: ejecutado |
| sin_cambios | 12.922 s | 11.156 s | recalibrate: omitido: revisión sin cambios; cross_league: omitido: revisión sin cambios; ml: omitido: revisión sin cambios |

Los dos ciclos finalizaron sin errores. El artefacto web contenía 36 partidos futuros; ML calculó 117 en su horizonte de diez días; la recalibración usó 487 observaciones y el modelo entre ligas 3.448 cruces. No se registraron apuestas ni pronósticos fiables nuevos en la copia. CPU acumulada suma los hilos del proceso; no es el porcentaje de CPU del PC. Se excluyen la copia inicial y la muestra de presión de cinco segundos. Una ejecución por caso, sin intervalo de confianza. El efecto no incluye la latencia de red de una recolección real ni demuestra el mismo ahorro cada jornada.

La revisión semántica recorriendo filas con JSON de Python costó 12,043 s y 7,344 s de CPU; por bloques serializados en SQLite costó 2,157 s y 2,000 s de CPU sobre la base real. No depende de mtime del SQLite/WAL: usa contenido ordenado de partidos y estadísticas, agregados de cuotas y predicciones de partidos terminados. Las predicciones futuras se controlan aparte para publicar el artefacto web sin forzar reentrenamiento. Reinsertar estadísticas idénticas o escribir live_scores no cambia la revisión; corregir resultados o estadísticas sí. Los agregados de cuotas son un detector operativo de cambios, no una prueba criptográfica de equivalencia de cada fila.

Prekickoff sin pendientes: **0,144 s**, CPU **0,125 s**, sin importar NumPy, pandas ni sklearn. Prueba sobre una base vacía aislada. Sale antes del muestreo de CPU y de los módulos pesados cuando no hay partidos en doce horas o cuotas pendientes.

### Presión del PC y prioridades

Prioridad 7 e IgnoreNew verificadas en las dos tareas del Programador de Windows, tras ejecutar `register_task.ps1` dos veces: mismos dos nombres, sin duplicados. Dentro del proceso: CPU BELOW_NORMAL e I/O background. CPU global > 60 % en una muestra de cinco segundos o estado Shell D3D, pantalla completa o presentación difieren el trabajo. Daily reintenta cada quince minutos hasta tres horas; no bloquea el lock de trabajo mientras espera. Prekickoff conserva la ejecución si un partido empieza en menos de noventa minutos; en otro caso espera al siguiente disparo de treinta minutos. Se registra cada decisión.

Hallazgo del ensayo descartado: background impuso un máximo duro de working set de 32 MiB. Se midieron unos 455.000 fallos de página/s y 1,84 GB privados, con ralentización masiva del ML. La versión final conserva CPU/I/O bajos y restaura los límites de working set previos, respetando los límites duros que ya existieran. Si no puede restaurarlos, revierte background y mantiene CPU baja; lo registra. Las pruebas nativas simulan ambos casos. El ensayo descartado no se usa como línea base.

Referencias de la implementación: [SetPriorityClass](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setpriorityclass) y [SetProcessWorkingSetSizeEx](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-setprocessworkingsetsizeex).

### Descarga e incrementalidad

Football-data conserva ETag, Last-Modified, contenido y hash en `data/cache/football_data`. 304 y 200 con contenido idéntico no se vuelven a parsear en daily si la ingesta ya fue confirmada. La confirmación se escribe solo después del commit SQLite y distingue el archivo de base por ruta/inodo; un fallo de parseo o de almacenamiento permite reintentar. La descarga normal conserva el contrato para scripts y tracking. Se avisó a Gustavo antes de modificar ingest; no se modificó `tracking.py` ni las matemáticas, horarios de captura o reglas de apuestas.

Los tres pasos de modelos guardan su revisión solo tras completar y reconstruyen un artefacto ausente. El fallo de uno no impide ejecutar los otros. La publicación web no vacía los predictores ni sus contextos; solo publica revisión nueva si cambian datos o predicciones.

### Operación

- `python scripts/automation.py status`: pausa vigente, última ejecución, pasos ejecutados/omitidos/diferidos y fechas UTC de última/próxima ejecución del Programador.
- `python scripts/automation.py pausa 2h`: pausa persistente que expira sola; también admite `30m`.
- `python scripts/automation.py reanudar`: elimina la pausa.
- Lock por tarea y lock global de trabajo, liberados por el sistema al terminar el proceso. No se solapan escrituras de daily y prekickoff.

Validación: **269 tests**, cobertura agéntica **94,35 %**, Ruff y ocho tests web en verde. Guardia, expiración, reintentos, urgencia, recuperación de artefactos, locks nativos y caché HTTP tienen regresiones sin esperas reales ni red.
