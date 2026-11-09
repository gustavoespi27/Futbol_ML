# Paso 1 — Wireframes para revisión

2026-11-09. Propuesta de estructura basada en la versión unificada de `docs/plan_frontend.md`.
**Pasos 2, 3 y wireframes aprobados. Paso 4 implementado en la rama, con validación propia de P0.**

Abrir [la galería local](index.html) en un navegador. No necesita servidor, red, fuentes externas ni instalación.
El selector permite alternar las variantes clara y oscura. Cada lámina se puede abrir a tamaño completo.

## Láminas

| Vista | Móvil | Escritorio |
|---|---|---|
| Hoy | [390 claro](hoy-390-claro.svg) · [oscuro](hoy-390-oscuro.svg) | [1440 claro](hoy-1440-claro.svg) · [oscuro](hoy-1440-oscuro.svg) |
| Hoy con datos atrasados | [390 claro](hoy-atrasado-390-claro.svg) · [oscuro](hoy-atrasado-390-oscuro.svg) | [1440 claro](hoy-atrasado-1440-claro.svg) · [oscuro](hoy-atrasado-1440-oscuro.svg) |
| Partidos | [390 claro](partidos-390-claro.svg) · [oscuro](partidos-390-oscuro.svg) | [1440 claro](partidos-1440-claro.svg) · [oscuro](partidos-1440-oscuro.svg) |
| Ficha | [390 claro](ficha-390-claro.svg) · [oscuro](ficha-390-oscuro.svg) | [1440 claro](ficha-1440-claro.svg) · [oscuro](ficha-1440-oscuro.svg) |
| Más | [390 claro](mas-390-claro.svg) · [oscuro](mas-390-oscuro.svg) | [1440 claro](mas-1440-claro.svg) · [oscuro](mas-1440-oscuro.svg) |

Son diez composiciones en dos temas, no dos propuestas visuales competidoras. Las de escritorio miden 1440×900;
las móviles tienen 390 px de ancho y muestran el recorrido completo: Hoy 1012 px de alto, Partidos/Más 964 y
ficha 1122. La altura no afirma que todo quepa en un viewport móvil: la implementación mantendrá un solo scroll
de página y navegación fija con área segura. Los tonos neutros marcan jerarquía; no fijan la paleta final.
Los valores entre corchetes
son campos del backend. No se muestran probabilidades, cuotas, montos, resultados ni fechas de captura inventados.

## Decisiones a revisar

- **Hoy:** estado → favoritos → dos indicadores → resumen → oportunidades. Favoritos muestra la situación sin
  selección, con acción para elegir equipos. Con selección ocupará el mismo bloque el próximo partido, hora
  y enlace a su ficha. Los indicadores propuestos son partidos de hoy y oportunidades con ventaja; ambos con
  periodo y universo. No presentar precisión histórica como indicador principal del día.
- **Partidos:** búsqueda y fechas accesibles; filtros adicionales en hoja móvil y barra de escritorio. Tres
  tarjetas representan una lista repetible, no el tamaño real del calendario. Un único scroll de página, con
  expansión/paginación al crecer. La selección de liga y fecha se resume; al activar filtros aparece «Limpiar».
- **Ficha:** vista completa dentro del área principal, no modal ni tabla de escritorio comprimida. Separar
  probabilidad y evaluación de precio. Los paneles de forma, tabla, cuotas y modelo se abren en el flujo de la
  página. Volver restaura filtros y posición. En esta fase no se propone una nueva ruta para el partido.
- **Más:** Fiabilidad y Cómo funciona dejan de perderse en móvil. Preferencias y asistente también están en la
  cabecera; Tema está en Más. El asistente se abrirá como hoja casi completa en móvil y panel lateral en
  escritorio, sin botón flotante que tape las tarjetas.

## Navegación sin romper rutas

| Destino nuevo | Ruta/vista que se conserva | Recorrido |
|---|---|---|
| Hoy | `#inicio` | Acceso a favoritos y próximos partidos |
| Partidos | `#partidos` | Lista → ficha existente → volver al mismo punto |
| Seguimiento | `#resultados` | Resultados y bitácora; filtros y periodo visibles |
| Explorar | `#simulador`, `#combinadas` | Selector de las dos herramientas, manteniendo sus enlaces directos |
| Más | `#rendimiento`, `#como-funciona` | Menú de acceso; preferencias y tema conservan sus mecanismos actuales |

La implementación del contenedor de Explorar/Más se define en el paso 6. Estos wireframes no inventan contratos
HTTP ni cambian hashes, IDs o acciones del producto. Los enlaces de la galería solo sirven para revisar láminas.

## Estados y recorridos móviles

La [galería](index.html#estados) contiene las cuatro variantes del mensaje compacto: datos atrasados, sin partidos,
sin oportunidades y error. No deben aparecer simultáneamente. Datos atrasados reemplaza resumen y oportunidades;
no se comunica que no hay valor por el solo hecho de no tener información.

| Situación | Tratamiento propuesto |
|---|---|
| Sin favoritos | Acción «Elegir mis equipos», sin una tarjeta vacía gigante |
| Muchos partidos / nombres largos | Tarjetas que crecen y salto de línea; no se reduce la fuente ni se corta el equipo |
| Carga lenta | Esqueleto del contenido, preservando filtros y navegación; no afirmar que no hay partidos |
| Ollama apagado | Asistente no disponible, indicando que el resto funciona; resumen por plantilla distinguible |
| Asistente ocupado | Estado de espera/cupo distinto de indisponibilidad; cancelación sin perder la consulta |
| Filtros móviles | Hoja con selección actual, Aplicar, Limpiar y Cerrar; Escape y retorno de foco al disparador |
| Teclado del chat | Campo de mensaje visible y hoja adaptada al área visual disponible; requiere prueba física posterior |

## Alcance y validación

Esta revisión solo cambia la documentación de este directorio. A2 y health están implementados en sus commits
separados; las láminas no implementan componentes del paso 4 ni cambian rutas o SSE.
La galería no consume servicios ni guarda preferencias.

Los SVG se generan con [generar_wireframes.py](generar_wireframes.py), usando solo la biblioteca estándar:

```powershell
.venv\Scripts\python docs/img/rediseno/generar_wireframes.py
```

La revisión de esta entrega evalúa jerarquía, contenido y recorridos. Las pruebas de la aplicación siguen
ejecutándose como exige el plan. Lighthouse, teclado virtual, zoom de producto y pruebas de lector de pantalla
de la interfaz definitiva corresponden a la implementación; los wireframes no prueban esas características.

Verificación realizada: 20 SVG con XML válido y sin texto fuera del lienzo en Chrome; galería a 360, 390 y
1440 px, ambos temas, con imágenes cargadas y sin desbordamiento horizontal ni excepciones JavaScript.
El script de la galería pasa `node --check`. Ruff pasa para el proyecto y el generador documental. La suite
del proyecto mantiene 212 pruebas en verde y 95,92% de cobertura de `footy_agents`.

Vistas previas rápidas: [Hoy móvil](vista-previa-hoy-movil.png) y
[Hoy escritorio](vista-previa-hoy-escritorio.png). Los SVG y la galería son la fuente de revisión completa.
Estado principal P0: [Hoy atrasado móvil](vista-previa-hoy-atrasado-movil.png) y
[Hoy atrasado escritorio](vista-previa-hoy-atrasado-escritorio.png).

## Ajustes de la revisión aprobada

- Hoy con datos atrasados: franja de advertencia con fecha, indicadores «— / en pausa» y un solo estado vacío
  que sustituye resumen y oportunidades. Se preservan favoritos guardados sin anunciar próximos partidos antiguos.
- Tarjetas de Hoy: badge «Con ventaja [+x%] · Pinnacle» o «Sin ventaja» como semáforo integrado, con etiqueta
  visible además de color. El badge no implica apostar automáticamente.
- Ficha: selección, cuota, precio justo, ventaja, monto sugerido y máximo 2% explícito. «Ver apuesta en
  Seguimiento» aparece solo cuando hay registro en papel; se conserva el contexto de vuelta.
- Vistas secundarias: una línea de estado, sin tarjeta destacada en condiciones normales. Una advertencia sí
  puede destacarse con el mismo patrón de Hoy; no se añade una segunda franja concurrente.
- «Asistente» completo en las cabeceras, marca «Fútbol ML», subtítulo de Partidos «Partidos, probabilidades
  y precio justo». La diferencia probabilidad/ventaja se explica al solicitar ayuda contextual (?), sin tarjeta
  permanente en Hoy. En móvil los accesos de cabecera pasan a una fila propia para conservar tamaño táctil.

## Indicaciones posteriores de implementación

Los ítems inactivos del menú lateral se implementan como texto sin borde, con relleno solo en el activo.
Los recuadros de navegación de las láminas no son el estilo definitivo del menú. El contraste, la tipografía y
la navegación de cinco destinos se trabajan en sus pasos correspondientes.

Pendiente del paso 11: unificar la tabla profesional del README con espacio antes de todos los porcentajes,
el 77 % de prueba en negrita y banca sin «,0». Esta corrección documental no se adelanta al paso 4.
