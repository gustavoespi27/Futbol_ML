# Arquitectura del agente

El LLM elige herramientas y redacta. El motor calcula las cifras. Los verificadores comprueban
procedencia numérica y algunas confusiones conocidas. El vigía persigue los objetivos sin usar un LLM.

## Resumen para la presentación

```mermaid
flowchart LR
    L[LLM decide] -->|Tools de lectura| M[Motor calcula]
    M --> V[Verificadores controlan]
    V --> R[Respuesta o respaldo]
    L -->|Objetivos persistentes| W[Vigía actúa sin LLM]
    J[Tareas y ejecución manual] --> W
    W --> A[Alertas y bitácora]
```

## Mapa operativo

```mermaid
flowchart TB
    U[Usuario: chat móvil o escritorio] --> API[Router: identidad y SSE]
    API --> R[routing.py: intención y continuidad]
    R -->|Seguimiento con match_id: precarga| T
    M[(memory.py: último turno y entidades)] --> R
    R --> L[LLM local: decide qué consultar o solicitar]
    L --> T[tools.py: argumentos Pydantic y permisos de acción]
    T -->|Solo lectura| E[Motor footy: probabilidades, Pinnacle, forma y métricas]
    T -->|Acción solicitada| W[watches.py: crear, listar, cancelar y favoritos]
    E --> O[observations.py: status, nota y opciones]
    W --> O
    O -->|Continuar o cambiar de camino| L
    L --> V[verify_numbers + check_claims]
    V -->|Un intento de reparación| L
    V -->|Válida| OUT[Respuesta y pasos visibles]
    V -->|Sigue inválida con datos útiles| F[fallback.py: frases canónicas verificadas]
    V -->|Sin datos útiles| ERR[SAFE_TEXT y done.success=false]
    ERR --> OUT
    F --> OUT
    W -->|Confirmación con ids reales verificada| OUT
    OUT -->|Solo respuestas verificadas| M
    API -->|Entidades incluso tras fallo| M
    API --> LOG[(agent_runs: herramientas, pasos y motivos)]

    JOB[daily / prekickoff / agent_watch.py] --> P[Vigía: percibir service.upcoming]
    P --> C[Comparar snapshot actual y anterior]
    S[(agent_watch_state)] --> C
    C --> D[Decidir: reglas y objetivos, prioridad y descartes]
    W --> OBJ[(agent_watches: objetivos activos)]
    OBJ --> D
    D --> A[Actuar: plantilla + facts + verify_numbers]
    A --> AL[(agent_alerts: alerta deduplicada)]
    A --> WL[(agent_watch_log: percepción, decisiones y motivos)]
    A --> S
    AL --> PANEL[Badge, alertas y bitácora del asistente]
    WL --> PANEL
    LOG --> PANEL
```

El diagrama separa dos ciclos:

- **Conversación:** el modelo decide dentro de las herramientas permitidas. Una escritura requiere
  intención explícita; crear una vigilancia exige identificar el objetivo. La confirmación usa el id
  persistido. La memoria conserva identidades aun tras un fallo, y solo recuerda respuestas verificadas.
  Un seguimiento con match_id consulta el análisis actualizado antes de la primera inferencia; ese
  resultado alimenta también el respaldo si la redacción no supera la verificación.
- **Vigía:** compara datos actuales con su memoria y los objetivos. Registra también decisiones de no
  actuar. Una transacción publica estado, alerta y objetivo cumplido; repetir el mismo ciclo no duplica
  alertas. Los textos son plantillas verificadas y nunca inicia ni consulta Ollama.

El motor y sus tablas permanecen fuera del alcance de escritura del agente. Las acciones afectan
únicamente `agent_*`; agregar favoritos modifica `agent_user_preferences`. El reset de demo admite
solo seis tablas y conserva preferencias. No hay órdenes de apuestas ni escrituras en `pro_bets`.

El respaldo necesita resultados útiles ya consultados. Los verificadores no demuestran corrección
semántica general: el modelo todavía puede elegir mal una herramienta, omitir una consulta o redactar
mal la cobertura. La bitácora permite distinguir estas situaciones de una respuesta válida y del
respaldo determinista.

Código: [orquestador](../src/footy_agents/orchestrator.py), [ruteo](../src/footy_agents/routing.py),
[observaciones](../src/footy_agents/observations.py), [memoria](../src/footy_agents/memory.py),
[respaldo](../src/footy_agents/fallback.py), [vigía](../src/footy_agents/watcher.py),
[persistencia](../src/footy_agents/watches.py). Evidencia y límites en
[08_capa_agentica.md](analisis/08_capa_agentica.md).


## Ojeador: delegación y tablero de cuotas

```mermaid
flowchart LR
    U[Usuario] --> M[El Míster: Qwen elige herramientas]
    M -->|request_odds con match_id real| O[El Ojeador: sin LLM]
    J[daily / prekickoff / CLI] --> O
    O --> P[Percibir: cobertura, favoritos, ids ESPN y antigüedad]
    P --> D[Decidir: agrupar liga-fecha y aplicar presupuesto]
    D -->|Seleccionados| E[Scoreboard ESPN: precios ofrecidos]
    D -->|Descartados con motivo| L[(agent_scout_log)]
    E -->|Calce exacto match_sources y validación prepartido| DB[(odds: tablero compartido)]
    E --> L
    DB --> C[Comparador: Pinnacle sin margen como única referencia]
    C -->|comparison_text verificado| M
    DB --> W[El Vigía: avisos existentes, sin LLM]
```

El Ojeador no consulta API-Football: registra que queda reservada para la ingesta diaria. La respuesta del
comparador usa su texto canónico completo o reparación/respaldo. Las casas publicadas por `espn_odds` se
excluyen de las referencias 1X2 y OU del contexto web; conservan su función de precio ofrecido para el motor profesional.
La revisión de datos se publica tras una inserción real y el panel recibe el refresco público. Una base temporal
no toca los cachés globales ni hace ese POST. `--dry-run` no consulta ESPN ni escribe la bitácora.
