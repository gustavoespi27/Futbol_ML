# Paso 4: confianza y vigencia de los datos

La interfaz distingue la vigencia de los datos, la disponibilidad del asistente y la versión del modelo. La franja usa `/api/overview` y `/api/agent/health`; comprueba su estado cada 60 segundos mientras la pestaña está visible y permite actualizar manualmente. No hace inferencias para comprobar la salud.

## Comportamiento implementado

- Desde 30 horas sin actualización, o sin fecha verificable, se pausan las vistas de recomendaciones. Hoy muestra indicadores «— / En pausa» y un único estado vacío. Los resultados y la evaluación histórica siguen accesibles desde sus vistas.
- Un fallo de consulta muestra un error con reintento. No se presenta como ausencia de partidos o de oportunidades.
- Se distinguen calendario vacío, falta de cuotas de Pinnacle y partidos con referencia pero sin ventaja. La falta de precio impide afirmar que no hay valor.
- Un resumen con `iterations=0` se identifica como «Resumen automático (sin IA)». Con datos atrasados no se solicitan partidos, sugerencias ni resumen. Sin referencia de precio se informa la limitación sin pedir redacción al asistente.
- Se retiran el chip «Motor activo» y la antigua línea lateral. La franja es compacta en vistas secundarias y destaca cuando hay advertencia. Los destinos laterales inactivos son texto sin borde; solo el activo tiene relleno.

La fecha se presenta en la zona `America/Santiago`. La vigencia se basa en `last_daily_run`, el dato disponible en el contrato actual: no certifica por separado que cada proveedor haya completado su actualización.

## Validación

- Suite Python completa: 212 pruebas; cobertura de `footy_agents`: 95,92 %. Ruff sin errores.
- Cuatro pruebas de reglas de presentación con `node:test`, incorporadas a CI: frontera de 30 horas, fechas inválidas o futuras, precedencia de estados y etiqueta de plantilla. Comprobación de sintaxis de los JavaScript modificados.
- Navegador Chromium: 42 capturas antes y 42 después, correspondientes a siete vistas, anchos 360/390/1440 y temas claro/oscuro. Sin errores de consola ni desbordamiento horizontal en la pasada final. Se corrigió un desbordamiento previo de 9 px en tarjetas históricas a 360 px.
- Otros 30 escenarios controlados verifican datos vigentes, atrasados, error, calendario vacío, fecha desconocida, falta de Pinnacle, fallo de salud, fallo de partidos, recuperación y transición de vigente a pausa. Los estados vacíos principales tienen una altura máxima observada de 119,2 px.
- Se comprobó que los casos atrasados y de error solo consultan fecha y salud; el calendario vacío no solicita el resumen. La recuperación vuelve a habilitar el contenido.

Los escenarios usan respuestas interceptadas en el navegador; no modifican la base de datos ni ejecutan inferencias. Las capturas de estados son ejemplos controlados, no evidencia de que los datos reales estén actualizados. Los registros completos y las capturas están en `reports/paso4/` (local, ignorado por Git). No se realizó una prueba en dispositivos físicos ni una auditoría Lighthouse.

## Evidencia visual seleccionada

| Vista | Captura |
| --- | --- |
| Antes, móvil claro | [Hoy a 390 px](img/paso4/antes-inicio-390-light.png) |
| Antes, escritorio oscuro | [Hoy a 1440 px](img/paso4/antes-inicio-1440-dark.png) |
| Datos atrasados, móvil claro | [Pausa a 390 px](img/paso4/estado-stale-390-light.png) |
| Datos atrasados, escritorio oscuro | [Pausa a 1440 px](img/paso4/estado-stale-1440-dark.png) |
| Datos vigentes, móvil claro | [Hoy a 390 px](img/paso4/estado-fresh-390-light.png) |
| Error con reintento | [Error a 390 px](img/paso4/estado-error-390-light.png) |
| Sin partidos | [Calendario vacío a 390 px](img/paso4/estado-empty-390-light.png) |
| Franja secundaria | [Partidos a 390 px](img/paso4/despues-partidos-390-dark.png) |

## Alcance posterior

Este paso no completa los cambios de tipografía, navegación, estructura de Hoy y ficha, ni el panel del asistente previstos en los pasos 5–9. Para el paso 11 queda registrada la corrección de la tabla profesional del README: `76 %` con espacio uniforme, `77 %` de prueba en negrita y banca sin `,0`.
