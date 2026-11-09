# Paso 8: vistas, fichas y acceso directo

La barra lateral de escritorio despliega las subsecciones del grupo activo: Explorar → Simulador/Combinadas; Más → Fiabilidad/Cómo funciona. Las rutas anteriores siguen vigentes. Hoy muestra una sola fecha en escritorio y probabilidades Local/Empate/Visita compactas en sus tres tarjetas; cuando no hay pronóstico muestra «—».

## Cambios por vista

- **Partidos**: resumen de selección y Limpiar; filtros en diálogo móvil, con Escape y retorno de foco. Las listas muestran diez filas y permiten ver todas sin un segundo scroll vertical.
- **Ficha**: equipos, competición, fecha, fuente y versión; probabilidades con etiquetas completas; «Ventaja de precio» calculada desde los datos de Pinnacle, con selección, cuota, precio justo, ventaja y monto sobre la banca guardada. Tope 2 % visible y límite diario 10 %. Sin Pinnacle no se atribuye ventaja al modelo. Forma, tabla, modelo y cuotas quedan en un desplegable. Se enlaza a Seguimiento cuando el registro está presente en la cartera devuelta por la API. Cerrar devuelve el foco y la posición a la lista.
- **Seguimiento**: filtro Todos/Aciertos/Fallos que permanece al volver. Las tablas pasan a tarjetas con etiquetas en móvil y muestran diez registros antes de ampliarse; el motivo de cada pronóstico permanece unido a su registro. Las cifras agregadas, pérdidas y CLV siguen visibles.
- **Simulador**: equipos → Calcular → resultado; antes de calcular hay una vista previa. Cuotas y monto son opcionales y están plegados; escritorio usa dos columnas. Reabrirlo no acumula manejadores de envío.
- **Combinadas**: alcance educativo explícito, sección histórica unificada y listas progresivas. Los valores orientativos del modelo no se presentan como una ventaja frente a Pinnacle.

No se cambian cálculos, base de datos ni contratos API/SSE. El importe de la ficha se calcula en JavaScript a partir del stake ya devuelto por el motor y la banca; el LLM no interviene.

## Verificación

- 218 pruebas Python, cobertura de agentes 96,07 %, ocho pruebas Node y Ruff correctos; sintaxis de los JavaScript modificados comprobada.
- 96 capturas antes y 96 después: ocho vistas, ambos temas, 360/390/1440 px, 768×1024, horizontal 844×390 y equivalencia 200 % (viewport CSS 720×450, escala 2). Sin desbordamiento horizontal ni excepciones de JavaScript en la pasada revisada; contraste de los pares DOM medidos correcto.
- Doce recorridos reales por tamaño/tema verifican cobertura única en Hoy, probabilidades compactas, apertura y cierre de fichas, recomendaciones, filtros, paginación, persistencia y cálculo del simulador. Los resultados del simulador también se comprueban después de calcular.
- Caso controlado: stake 2 % sobre $100.000 se presenta como $2.000 con referencia Pinnacle; es una prueba de presentación, no una apuesta real.
- Comprobación específica: reabrir el simulador dos veces y calcular produce una sola petición de predicción.
- Se corrigió un desbordamiento del resultado del simulador causado por el ancho mínimo intrínseco de sus tarjetas. La descarga diferida de Chart.js y el trabajo de rendimiento siguen reservados al paso 10.

Las capturas y registros completos están en `reports/paso8/` (local, ignorado por Git). La ampliación se prueba mediante viewport y escala equivalentes, no con el control de zoom de la ventana. No se reportan mediciones Lighthouse ni pruebas en un teléfono físico.

## Capturas seleccionadas

| Vista | Evidencia |
| --- | --- |
| Antes: Hoy en escritorio | [1440 oscuro](img/paso8/antes-hoy-1440-dark.png) |
| Antes: Partidos en móvil | [390 claro](img/paso8/antes-partidos-390-light.png) |
| Hoy en escritorio, fecha única y probabilidades | [1440 oscuro](img/paso8/hoy-1440-dark.png) |
| Partidos en móvil | [390 claro](img/paso8/partidos-390-light.png) |
| Filtros móviles | [Diálogo](img/paso8/filtros-390-light.png) |
| Ficha en móvil, estado sin referencia | [Ficha](img/paso8/ficha-390-light.png) |
| Seguimiento en móvil | [Tarjetas](img/paso8/seguimiento-390-light.png) |
| Simulador en escritorio | [Dos columnas](img/paso8/simulador-1440-dark.png) |
| Más en escritorio | [Subsecciones](img/paso8/mas-1440-dark.png) |

La siguiente tarea aprobada es A: pulido del chat, antes de B1/B2, A3 selecciones y los pasos 9–11. Las capturas finales con internacionales cubiertos corresponden al paso 11, después de A3.
