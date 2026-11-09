
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
