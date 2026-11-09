# Paso 5: tokens, tipografía y montos

Se mantiene la estructura de las vistas y se actualiza su base visual: Inter 400/600/700, cifras tabulares, títulos sin espaciado menor que −0,01 em y tokens de espacio de 4 a 48 px. La escala de texto es 12/13/15/16/20/28 px; los indicadores grandes conservan tamaños específicos. Los campos de texto usan 16 px para facilitar la lectura móvil. JetBrains Mono 500 queda limitado al código.

El color del relleno de botones se separa del texto de acento y del foco. Se corrigen los textos secundarios, las advertencias, los filtros activos, las barras de probabilidad y las iniciales de escudos sin imagen. El riel lateral conserva su fondo oscuro en ambos temas y sus colores se declaran como excepción local. Los ítems inactivos siguen sin borde ni relleno.

Los montos se presentan con `Intl.NumberFormat("es-CL")`: `$100.000` y `100.000` dentro del campo. Al enfocar, desaparecen los separadores de miles; al salir, vuelven. Se conserva el número para el cálculo y almacenamiento, se admite coma decimal y un valor inválido no reemplaza la banca o el monto guardado. El formato monetario CLP redondea la presentación a pesos; el campo conserva los decimales del valor editado. No se cambian las fórmulas, límites de riesgo ni contratos API/SSE.

## Contraste medido

Ratios WCAG calculados a partir de luminancia relativa sRGB. La columna indica el mínimo entre fondo de página y superficies 1/2/3; los tokens tienen también un comentario con estos resultados en el CSS.

| Texto o foco | Oscuro | Claro |
| --- | ---: | ---: |
| Principal | 13,60:1 | 12,93:1 |
| Secundario | 7,63:1 | 7,50:1 |
| Atenuado | 6,64:1 | 5,49:1 |
| Acento / positivo | 7,79:1 | 4,75:1 |
| Negativo | 5,56:1 | 4,69:1 |
| Advertencia | 7,81:1 | 4,96:1 |
| Mercado | 6,97:1 | 4,96:1 |
| Modelo | 6,17:1 | 4,86:1 |
| Foco | 9,82:1 | 4,75:1 |

En ambos temas, blanco sobre el botón esmeralda y la barra local mide 5,48:1; sobre empate, 7,58:1; sobre visita, 7,09:1. La auditoría del DOM compone los fondos transparentes antes de comparar texto normal con 4,5:1 y texto grande con 3:1. Los problemas originales incluían texto atenuado a 3,84:1 y blanco sobre esmeralda a 2,54:1.

## Verificación y evidencia

- 218 pruebas Python, cobertura de `footy_agents` 96,07 %, Ruff sin errores; ocho pruebas Node y comprobación de sintaxis de los cuatro JavaScript modificados.
- Siete vistas, anchos 360/390/1440 px y temas claro/oscuro: 42 capturas antes y 42 después. Sin desbordamiento horizontal ni excepciones de JavaScript en la pasada final.
- Contraste del DOM en las siete vistas de escritorio en ambos temas: sin infracciones en los pares medidos.
- Interacciones en los tres anchos y ambos temas: ficha desplegada, selector de ligas abierto, preferencias, asistente y simulador; además, edición de banca y monto. Se comprueba que `250000` se presenta como `250.000` y se guarda como `250000`, y que un valor negativo no sustituye la banca guardada.
- Estados controlados de datos atrasados, error, calendario vacío, recuperación y pérdida de vigencia. Se conserva la pausa de recomendaciones y los vacíos compactos.

Las pruebas se realizaron con Chromium mediante CDP, sin dependencias nuevas. Los registros y todas las capturas están en `reports/paso5/` y `reports/paso4/` (locales, ignorados por Git). Los estados controlados interceptan respuestas del navegador y no alteran la base de datos. No se midió Lighthouse ni se probó en un teléfono físico; esta comprobación de contraste no equivale a una auditoría completa con lector de pantalla.

| Ejemplo | Antes | Después |
| --- | --- | --- |
| Hoy móvil claro | [390 px](img/paso5/antes-inicio-390-light.png) | [390 px](img/paso5/despues-inicio-390-light.png) |
| Hoy escritorio oscuro | [1440 px](img/paso5/antes-inicio-1440-dark.png) | [1440 px](img/paso5/despues-inicio-1440-dark.png) |
| Partidos móvil oscuro | [390 px](img/paso5/antes-partidos-390-dark.png) | [390 px](img/paso5/despues-partidos-390-dark.png) |
| Preferencias móvil claro | — | [390 px](img/paso5/preferencias-390-light.png) |
| Asistente móvil oscuro | — | [390 px](img/paso5/asistente-390-dark.png) |

La nueva navegación corresponde al paso 6; la reducción de Hoy al 7; las tarjetas y tablas móviles al 8. Se mantienen esos pendientes, la carga diferida del paso 10 y el ajuste de la tabla profesional del README del paso 11.
