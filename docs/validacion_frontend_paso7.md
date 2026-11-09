# Paso 7: Hoy, favoritos y cobertura única

Hoy queda organizado en cinco bloques: estado de datos, favoritos, dos indicadores, resumen y hasta tres partidos para revisar. No contiene gráficos ni registros históricos. Los indicadores cuentan el **calendario próximo**, coherentemente con los partidos que entrega la API; no se presentan los 40 partidos de varios días como si todos se jugaran hoy.

La cobertura de Pinnacle aparece **solo en el resumen**. Se retiran su repetición en el indicador, la línea sobre recomendaciones y el vacío de Hoy. La ficha de hechos y el texto del backend no se modifican: siguen distinguiendo el calendario completo de las próximas 24 horas y limitando la ausencia de ventaja a los partidos evaluables. Cada tarjeta informa el estado de su propio partido: «Con ventaja … · Pinnacle», «Sin ventaja detectada» o «Sin referencia de precio», con texto y semáforo.

## Distribución y carga

| Contenido | Destino |
| --- | --- |
| Favoritos, dos indicadores, resumen y tres tarjetas | Hoy |
| Recomendaciones detalladas, monto de referencia, más fiables y semáforo completo | Partidos → Recomendaciones y semáforo |
| Bitácora de apuestas y pronósticos registrados | Seguimiento |
| Precisión en vivo, ajuste automático, respaldo histórico y calibración trasladados | Fiabilidad |

Las recomendaciones detalladas se consultan al desplegarlas en Partidos. El resumen se solicita al entrar en Hoy y se cancela al salir; abrir una vista histórica directamente no lo solicita. Fiabilidad y Seguimiento cargan sus datos al entrar directamente y conservan los registros cuando las recomendaciones están en pausa. Los textos de riesgo, las pérdidas y el CLV permanecen en sus vistas; no se cambian cifras, API/SSE ni fórmulas.

Favoritos muestra el próximo partido de los equipos guardados, o una acción para elegirlos. Guardar preferencias actualiza Hoy y el resumen. Las tarjetas priorizan partidos con selección que cumple la regla, después favoritos y luego fecha; abrir una tarjeta lleva a su ficha existente en Partidos. Una selección excluida por la regla no oculta otra selección elegible del mismo partido.

## Verificación

- 218 pruebas Python, cobertura de agentes 96,07 %, ocho pruebas Node y Ruff correctos. Sintaxis de `app.js`, `suggestions.js` y `agent.js` comprobada.
- 48 capturas antes y 48 después de Hoy, Partidos, Seguimiento y Fiabilidad: ambos temas, 360/390/1440 px, 768×1024, horizontal 844×390 y equivalencia de ampliación 200 % (viewport CSS 720×450, escala 2). Sin desbordamiento horizontal, infracciones en los pares de contraste DOM medidos ni excepciones de JavaScript.
- Doce recorridos de tamaño/tema comprueban cobertura única, dos indicadores, un máximo de tres tarjetas, cero gráficos en Hoy, apertura de la ficha, carga del análisis desplegable y registros y métricas en sus destinos.
- Cuarenta casos controlados cubren datos atrasados, error, calendario vacío, cobertura nula/parcial/completa, favoritos, nombres largos, carga lenta y fallo de preferencias. Los estados P0 mantienen un único vacío compacto y no solicitan recomendaciones con datos atrasados. Se comprueba además una tarjeta con selección elegible y la entrada directa a ambas vistas históricas con datos atrasados.
- **Actualizar mide 44 px de alto** en las comprobaciones móviles, tanto en Hoy como en los estados compactos o de advertencia comprobados en las vistas históricas. La regla `min-height: 44px` ya estaba presente y se mantiene.
- Como referencia de tamaño con datos reales, la pasada funcional final midió Hoy en aproximadamente 1333 px a 390 px y 764 px en escritorio a 1440 px, con dos indicadores y tres tarjetas. Son alturas de contenido, no métricas de tiempo de carga ni de memoria.

Los registros completos están en `reports/paso7/`, ignorado por Git. Los casos controlados interceptan respuestas solo en el navegador y no modifican la base de datos. No se midió Lighthouse ni se probó en un dispositivo físico. Chart.js sigue cargándose desde el encabezado; su descarga diferida corresponde al paso 10.

## Capturas seleccionadas

| Vista | Antes | Después |
| --- | --- | --- |
| Hoy, móvil claro | [390 px](img/paso7/antes-hoy-390-light.png) | [390 px](img/paso7/hoy-390-light.png) |
| Tarjetas de Hoy, móvil claro | — | [Tramo inferior a 390 px](img/paso7/hoy-revision-390-light.png) |
| Hoy, escritorio oscuro | [1440 px](img/paso7/antes-hoy-1440-dark.png) | [1440 px](img/paso7/hoy-1440-dark.png) |
| Seguimiento, móvil claro | — | [Bitácora](img/paso7/seguimiento-390-light.png) |
| Fiabilidad, móvil oscuro | — | [Históricos trasladados](img/paso7/fiabilidad-390-dark.png) |
| Hoy, tableta clara | — | [768 px](img/paso7/hoy-768-light.png) |
| Hoy, horizontal claro | — | [844×390](img/paso7/hoy-horizontal-light.png) |
| Hoy, ampliación equivalente a 200 % | — | [Escala 2](img/paso7/hoy-200-light.png) |

## Indicación para el paso 8

En escritorio, mostrar bajo el grupo lateral activo sus subsecciones: **Explorar → Simulador, Combinadas** y **Más → Fiabilidad, Cómo funciona**, para evitar dos clics. Se conserva esta indicación para el siguiente paso, junto con la revisión de tablas y fichas móviles. El panel del asistente corresponde al paso 9 y el ajuste pendiente de la tabla profesional del README, al 11.
