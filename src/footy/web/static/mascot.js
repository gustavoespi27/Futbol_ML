/* El Míster: mascota del asistente. Un zorro DT («el zorro del banco»), dibujado en SVG propio.
   Dos variantes: cabeza (avatar, botón flotante, estados vacíos) y cuerpo entero (saludo del chat).
   Colores en clases .fx-* de styles.css para calzar con el tema; animaciones solo sin «reducir movimiento». */

// Tierno pero inconfundiblemente zorro: hocico en punta con la nariz en la punta, orejas altas con puntas oscuras,
// ojos grandes con brillo, mechón y rubor suave. La ceja derecha más alta le da el toque pícaro de DT.
// Cordón y silbato van aparte (en el cuerpo entero el silbato cuelga sobre la chaqueta).
const FOX_CORD = `
  <path class="fx-cord" d="M16 46 Q32 74 48 46"/>
  <g class="fx-whistle"><rect class="fx-metal" x="27.5" y="60" width="9" height="5.5" rx="2.7"/><circle class="fx-metal" cx="29" cy="65" r="2.4"/></g>`;
const FOX_HEAD = `
  <g class="fx-ear fx-ear-l"><path class="fx-fur fx-line" d="M9 30 Q6.5 11 12.5 -1 Q23 5.5 30 15.5 Z"/>
    <path class="fx-inner" d="M13.5 25 Q11.5 13 14 5.5 Q20.5 10 25 16.5 Z"/><path class="fx-tip" d="M10.6 7.5 Q11.3 2.5 12.5 -1 Q16.8 1.6 20 4.4 Q14.5 4.8 10.6 7.5 Z"/></g>
  <g class="fx-ear fx-ear-r"><path class="fx-fur fx-line" d="M55 30 Q57.5 11 51.5 -1 Q41 5.5 34 15.5 Z"/>
    <path class="fx-inner" d="M50.5 25 Q52.5 13 50 5.5 Q43.5 10 39 16.5 Z"/><path class="fx-tip" d="M53.4 7.5 Q52.7 2.5 51.5 -1 Q47.2 1.6 44 4.4 Q49.5 4.8 53.4 7.5 Z"/></g>
  <path class="fx-fur" d="FACE"/>
  <path class="fx-white" d="M6.8 33.5 C14 34.5 22 36.5 27 42.5 Q32 46.5 37 42.5 C42 36.5 50 34.5 57.2 33.5 C55.6 38 52.6 41.4 49 44 C43.5 48.5 37.5 54 32 59.5 C26.5 54 20.5 48.5 15 44 C11.4 41.4 8.4 38 6.8 33.5 Z"/>
  <path class="fx-line" fill="none" d="FACE"/>
  <path class="fx-fur fx-line" d="M28.5 12.5 Q29 5 35 5.5 Q32 8 33.8 12.2 Z"/>
  <ellipse class="fx-blush" cx="15.5" cy="38.5" rx="3.2" ry="2"/><ellipse class="fx-blush" cx="48.5" cy="38.5" rx="3.2" ry="2"/>
  <path class="fx-brow" d="M17 23.2 Q21 21.2 25 22.8 M39 21.6 Q43 19.8 47 21.8"/>
  <g class="fx-eyes"><ellipse class="fx-ink" cx="21.5" cy="30.5" rx="4.3" ry="5.1"/><ellipse class="fx-ink" cx="42.5" cy="30.5" rx="4.3" ry="5.1"/>
    <circle class="fx-white" cx="23" cy="28.4" r="1.75"/><circle class="fx-white" cx="44" cy="28.4" r="1.75"/>
    <circle class="fx-white" cx="20" cy="32.8" r=".8"/><circle class="fx-white" cx="41" cy="32.8" r=".8"/></g>
  <ellipse class="fx-ink" cx="32" cy="46.8" rx="3.4" ry="2.5"/><circle class="fx-white" cx="31" cy="46" r=".75"/>
  <path class="fx-smile" d="M28.8 50.6 Q32.6 53.6 36.4 50"/>`.replaceAll("FACE", "M6 29 C6 17 18 11 32 11 C46 11 58 17 58 29 C58 35 54.5 40 49 44 C43.5 48.5 37.5 54 32 59.5 C26.5 54 20.5 48.5 15 44 C9.5 40 6 35 6 29 Z");

// Cuerpo chibi: cabeza grande sobre un cuerpo pequeño y redondo, patitas, cola esponjosa y pizarra táctica.
const FOX_BODY = `
  <g class="fx-tail"><path class="fx-fur fx-line" d="M84 122 C116 124 128 94 112 66 C104 70 102 80 104 88 C102 100 94 106 82 108 Z"/>
    <path class="fx-white" d="M112 66 C120 76 121 88 117 96 C111 92 105 90 104 88 C102 80 104 70 112 66 Z"/>
    <path class="fx-line" fill="none" d="M104 88 C110 89 114 92 117 96"/></g>
  <ellipse class="fx-paw" cx="49" cy="127" rx="9" ry="5"/><ellipse class="fx-paw" cx="75" cy="127" rx="9" ry="5"/>
  <path class="fx-jacket fx-line" d="M42 76 C34 80 31 93 31.5 106 Q32.5 126 62 126 Q91.5 126 92.5 106 C93 93 90 80 82 76 Z"/>
  <path class="fx-white" d="M53 75 L62 89 L71 75 Z"/>
  <path class="fx-seam" d="M53 75 L62 89 L71 75 M62 89 L62 125"/>
  <path class="fx-cord" d="M54 77 Q62 101 70 77"/>
  <g class="fx-whistle fx-whistle-body"><rect class="fx-metal" x="57.5" y="90" width="10" height="6" rx="3"/><circle class="fx-metal" cx="59.5" cy="95.5" r="2.6"/></g>
  <g class="fx-board"><rect class="fx-ink" x="64" y="100" width="38" height="25" rx="4"/><rect class="fx-pitch" x="66.5" y="102.5" width="33" height="20" rx="2"/>
    <path class="fx-chalk" d="M83 102.5 V122.5 M70 106 l3.2 3.2 m0 -3.2 l-3.2 3.2 M73 117 Q82 109 92 113"/><circle class="fx-chalk" cx="83" cy="112.5" r="3.4"/>
    <circle class="fx-chalk" cx="94.5" cy="117" r="2.2"/></g>
  <ellipse class="fx-paw" cx="66" cy="106" rx="6" ry="5"/>
  <ellipse class="fx-paw" cx="100" cy="109" rx="5.5" ry="4.6"/>
  <g transform="translate(15.5 -1) scale(1.45)">${FOX_HEAD}</g>`;

function misterFace(size = 32, extra = "") {
  return `<svg class="mister mister-face ${extra}" width="${size}" height="${size}" viewBox="1 -3.5 62 71.5" aria-hidden="true" focusable="false">${FOX_CORD}${FOX_HEAD}</svg>`;
}
function misterFull(size = 96, extra = "") {
  return `<svg class="mister mister-full ${extra}" width="${size}" height="${Math.round(size * 136 / 124)}" viewBox="0 -4 124 136" aria-hidden="true" focusable="false">${FOX_BODY}</svg>`;
}
// Frase con el Míster para estados vacíos: el texto lo pone quien llama (siempre un hecho del sistema, sin cifras inventadas).
function misterQuote(text, size = 44) {
  return `<div class="mister-quote">${misterFace(size)}<p>${text}</p></div>`;
}
// El Míster «piensa» mientras el chat espera respuesta (mira a los lados y para las orejas).
function misterThinking(on) {
  document.querySelectorAll(".mister-live").forEach((el) => el.classList.toggle("is-thinking", on));
}

// Ranuras estáticas del HTML: <span data-mister="face|full" data-size="..."></span>
document.querySelectorAll("[data-mister]").forEach((slot) => {
  const size = Number(slot.dataset.size) || undefined;
  slot.innerHTML = slot.dataset.mister === "full" ? misterFull(size) : misterFace(size);
});
