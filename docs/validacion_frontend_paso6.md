# Paso 6: navegación y marca

La barra lateral y la barra inferior comparten cinco destinos: **Hoy, Partidos, Seguimiento, Explorar y Más**. Los destinos laterales inactivos siguen como texto sin borde ni relleno. La marca es **Fútbol ML**, sin el subtítulo «PRO ANALYTICS», y el inicio se titula **Hoy**.

## Rutas y acciones

| Destino | Ruta conservada o añadida | Contenido |
| --- | --- | --- |
| Hoy | `#inicio` | Panel actual; su reducción corresponde al paso 7 |
| Partidos | `#partidos` | Calendario y fichas actuales |
| Seguimiento | `#resultados` | Resultados actuales; la bitácora se moverá en el paso 7 |
| Explorar | `#explorar` | Acceso a `#simulador` y `#combinadas` |
| Más | `#mas` | Fiabilidad (`#rendimiento`), Cómo funciona (`#como-funciona`), preferencias, tema y asistente |

Simulador y Combinadas mantienen «Explorar» seleccionado; Fiabilidad y Cómo funciona mantienen «Más». Los enlaces directos existentes y el historial del navegador conservan su función. El enlace antiguo `#sugeridas` sigue entrando a Hoy.

Las opciones de Más usan enlaces y botones nativos. Se informa la ubicación con `aria-current`, se enfoca la cabecera al cambiar de vista y se conserva el enlace «Saltar al contenido». Abrir `/#main` directamente muestra Hoy; al usar ese salto desde otra vista se conserva su contenido y su actualización. El asistente devuelve el foco a quien lo abrió, incluido el botón de Más, al cerrarlo con Escape. El diálogo de preferencias conserva su cierre y retorno de foco nativos.

La barra móvil reserva el área segura inferior y sus destinos superan 44×44 px. «Seguimiento» tiene un ancho mínimo de 76 px para que quepa a 12 px sin invadir los destinos vecinos. Más y Explorar usan el desplazamiento normal de la página.

## Validación

- 218 pruebas Python y ocho pruebas Node correctas; cobertura de `footy_agents`: 96,07 %. Ruff y comprobación de sintaxis de `app.js` y `agent.js` sin errores.
- Antes: 84 capturas de las siete vistas existentes. Después: 108 capturas de las nueve vistas, incluidos Más y Explorar. Ambos temas, anchos 360/390/1440 px, tableta a 768×1024, horizontal a 844×390 y equivalencia de ampliación 200 %.
- La equivalencia de 200 % usa un viewport CSS de 720×450 y escala de dispositivo 2, con una imagen de 1440×900. Comprueba tamaño y distribución equivalentes; no es una medición del control de zoom de la interfaz del navegador.
- Sin desbordamiento horizontal ni excepciones de JavaScript en las pasadas finales. Contraste del texto DOM comprobado con composición de fondos en ambos temas.
- Doce combinaciones de tamaño/tema verifican los cinco destinos, áreas táctiles, texto dentro de cada destino, selección de grupos, Enter sobre enlaces, historial atrás/adelante, cambio de tema y apertura/cierre de preferencias y asistente con retorno de foco.
- Apertura directa de once rutas, incluidas las siete existentes, las dos nuevas, `#main` y `#sugeridas`; se comprueba la vista visible y el título de la marca.
- Cinco estados controlados de Más: datos atrasados, fallo de actualización, calendario vacío, carga lenta y fallo de preferencias, con el asistente local no disponible. Se conservan los accesos, el estado de advertencia y el error con posibilidad de volver a intentar.

Los registros y capturas completos están en `reports/paso6/` y las capturas principales anteriores en `reports/paso4/antes6-*` (locales, ignorados por Git). Las capturas adicionales anteriores usan el HTML, CSS y JavaScript del commit aprobado `72ddc56`, interceptados solo en el navegador, con las mismas API locales. No se guardan preferencias en el servidor ni se envían mensajes al asistente en estas comprobaciones. No se añaden dependencias ni se modifican contratos API/SSE o cálculos del motor.

## Capturas seleccionadas

| Ejemplo | Evidencia |
| --- | --- |
| Navegación anterior, móvil claro | [Antes, 390 px](img/paso6/antes-inicio-390-light.png) |
| Hoy con la nueva marca, móvil claro | [Después, 390 px](img/paso6/hoy-390-light.png) |
| Navegación anterior, escritorio oscuro | [Antes, 1440 px](img/paso6/antes-inicio-1440-dark.png) |
| Más con barra lateral, escritorio oscuro | [Después, 1440 px](img/paso6/mas-1440-dark.png) |
| Más, móvil oscuro | [360 px](img/paso6/mas-360-dark.png) |
| Más, móvil claro | [390 px](img/paso6/mas-390-light.png) |
| Explorar, móvil claro | [390 px](img/paso6/explorar-390-light.png) |
| Más, tableta | [768 px](img/paso6/mas-768-light.png) |
| Más, horizontal | [844×390](img/paso6/mas-horizontal-light.png) |
| Más, ampliación equivalente a 200 % | [Viewport 720×450 a escala 2](img/paso6/mas-200-light.png) |

## Próximo paso

En el paso 7 se mostrará la cobertura de Pinnacle **una sola vez en Hoy**, conforme a la revisión de Gustavo: actualmente se repite en el resumen, sobre la tarjeta y dentro de ella. La ficha de hechos debe conservar la cobertura y las conclusiones deben seguir limitadas a los partidos evaluables. También siguen pendientes el traslado de históricos y bitácora, y el rediseño de tablas, fichas y chat de los pasos 8–9. Los contenedores de listas heredados conservan su desplazamiento interno hasta esa revisión de vistas. No se adelantan en este commit.
