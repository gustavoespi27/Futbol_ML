
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
