/* El Míster: mascota del asistente. Un zorro DT («el zorro del banco»), dibujado en SVG propio.
   Dos variantes: cabeza (avatar, botón flotante, estados vacíos) y cuerpo entero (saludo del chat).
   Colores en clases .fx-* de styles.css para calzar con el tema; animaciones solo sin «reducir movimiento». */

// Estilo tierno: cabeza redonda con mejillas esponjosas, ojos grandes con brillo, rubor y sonrisa en «w».
// La ceja derecha un poco más alta le da el toque pícaro de DT. Cordón y silbato van aparte (en el cuerpo
// entero el silbato cuelga sobre la chaqueta).
const FOX_CORD = `
  <path class="fx-cord" d="M17 51 Q32 73 47 51"/>
  <g class="fx-whistle"><rect class="fx-metal" x="27.5" y="59.5" width="9" height="5.5" rx="2.7"/><circle class="fx-metal" cx="29" cy="64.5" r="2.4"/></g>`;
const FOX_HEAD = `
  <g class="fx-ear fx-ear-l"><path class="fx-fur fx-line" d="M10 30 Q5 11 12.5 3 Q22 7.5 30 17.5 Z"/><path class="fx-inner" d="M14 25 Q11.5 13.5 14.5 8.5 Q20.5 12 25 18 Z"/></g>
  <g class="fx-ear fx-ear-r"><path class="fx-fur fx-line" d="M54 30 Q59 11 51.5 3 Q42 7.5 34 17.5 Z"/><path class="fx-inner" d="M50 25 Q52.5 13.5 49.5 8.5 Q43.5 12 39 18 Z"/></g>
  <path class="fx-fur" d="FACE"/>
  <path class="fx-white" d="M9 38.5 C15 36.5 23 38 27.5 44 Q32 47.5 36.5 44 C41 38 49 36.5 55 38.5 C54 44.5 49.5 50.5 44 54 C40.5 57 36.5 58.5 32 58.5 C27.5 58.5 23.5 57 20 54 C14.5 50.5 10 44.5 9 38.5 Z"/>
  <path class="fx-line" fill="none" d="FACE"/>
  <path class="fx-fur fx-line" d="M28.5 14.5 Q29 7 35 7.5 Q32 10 33.8 14.2 Z"/>
  <ellipse class="fx-blush" cx="13.8" cy="42" rx="4" ry="2.5"/><ellipse class="fx-blush" cx="50.2" cy="42" rx="4" ry="2.5"/>
  <path class="fx-brow" d="M17.5 25.6 Q21.5 23.4 25.5 25.2 M38.5 23.8 Q42.5 22 46.5 24"/>
  <g class="fx-eyes"><ellipse class="fx-ink" cx="21.5" cy="33.5" rx="4.7" ry="5.5"/><ellipse class="fx-ink" cx="42.5" cy="33.5" rx="4.7" ry="5.5"/>
    <circle class="fx-white" cx="23.2" cy="31.3" r="1.9"/><circle class="fx-white" cx="44.2" cy="31.3" r="1.9"/>
    <circle class="fx-white" cx="19.9" cy="36" r=".9"/><circle class="fx-white" cx="40.9" cy="36" r=".9"/></g>
  <path class="fx-ink" d="M29.4 43.6 Q32 42 34.6 43.6 Q33.4 46.2 32 46.2 Q30.6 46.2 29.4 43.6 Z"/>
  <path class="fx-smile" d="M28.6 48 Q30.3 50.6 32 48.6 Q33.7 50.6 35.4 48"/>`.replaceAll("FACE", "M6 33 C6 20 18 13 32 13 C46 13 58 20 58 33 C58 39 55.5 44 51 47.5 L55.5 50.5 L47.5 52 C43.5 56 38 58.5 32 58.5 C26 58.5 20.5 56 16.5 52 L8.5 50.5 L13 47.5 C8.5 44 6 39 6 33 Z");

// Cuerpo chibi: cabeza grande sobre un cuerpo pequeño y redondo, patitas, cola esponjosa y pizarra táctica.
const FOX_BODY = `
  <path class="fx-tail fx-fur fx-line" d="M86 121 C114 120 124 92 108 70 C106 90 99 102 84 106 Z"/>
  <path class="fx-tail fx-white" d="M108 70 C116.5 78 117 91 113 99 C109 91 106.5 80 108 70 Z"/>
  <ellipse class="fx-paw" cx="49" cy="127" rx="9" ry="5"/><ellipse class="fx-paw" cx="75" cy="127" rx="9" ry="5"/>
  <path class="fx-jacket fx-line" d="M42 76 C34 80 31 93 31.5 106 Q32.5 126 62 126 Q91.5 126 92.5 106 C93 93 90 80 82 76 Z"/>
  <path class="fx-white" d="M53 75 L62 89 L71 75 Z"/>
  <path class="fx-seam" d="M53 75 L62 89 L71 75 M62 89 L62 125"/>
  <path class="fx-cord" d="M54 77 Q62 101 70 77"/>
  <g class="fx-whistle fx-whistle-body"><rect class="fx-metal" x="57.5" y="90" width="10" height="6" rx="3"/><circle class="fx-metal" cx="59.5" cy="95.5" r="2.6"/></g>
  <g class="fx-board"><rect class="fx-ink" x="64" y="100" width="38" height="25" rx="4"/><rect class="fx-pitch" x="66.5" y="102.5" width="33" height="20" rx="2"/>
    <path class="fx-chalk" d="M83 102.5 V122.5 M70 106 l3.2 3.2 m0 -3.2 l-3.2 3.2 M73 117 Q82 109 92 113"/><circle class="fx-chalk" cx="83" cy="112.5" r="3.4"/>
    <circle class="fx-chalk" cx="94.5" cy="117" r="2.2"/></g>
  <ellipse class="fx-fur fx-line" cx="66" cy="106" rx="6" ry="5"/>
  <ellipse class="fx-fur fx-line" cx="100" cy="109" rx="5.5" ry="4.6"/>
  <g transform="translate(15.5 -5) scale(1.45)">${FOX_HEAD}</g>`;

function misterFace(size = 32, extra = "") {
  return `<svg class="mister mister-face ${extra}" width="${size}" height="${size}" viewBox="1 -2 62 70" aria-hidden="true" focusable="false">${FOX_CORD}${FOX_HEAD}</svg>`;
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
