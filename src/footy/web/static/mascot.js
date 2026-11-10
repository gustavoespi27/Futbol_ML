/* El Míster: mascota del asistente. Un zorro DT («el zorro del banco»), dibujado en SVG propio.
   Dos variantes: cabeza (avatar, botón flotante, estados vacíos) y cuerpo entero (saludo del chat).
   Colores en clases .fx-* de styles.css para calzar con el tema; animaciones solo sin «reducir movimiento». */

// Cordón y silbato van aparte: en el cuerpo entero el silbato cuelga sobre la chaqueta.
const FOX_CORD = `
  <path class="fx-cord" d="M16 50 Q32 75 48 50"/>
  <g class="fx-whistle"><rect class="fx-metal" x="27.5" y="59" width="9" height="5.5" rx="2.5"/><circle class="fx-metal" cx="29" cy="64" r="2.4"/></g>`;
const FOX_HEAD = `
  <g class="fx-ear fx-ear-l"><path class="fx-fur fx-line" d="M9 31 L11 0 L31 17 Z"/><path class="fx-inner" d="M14.5 24.5 L15 7.5 L25.5 18 Z"/></g>
  <g class="fx-ear fx-ear-r"><path class="fx-fur fx-line" d="M55 31 L53 0 L33 17 Z"/><path class="fx-inner" d="M49.5 24.5 L49 7.5 L38.5 18 Z"/></g>
  <path class="fx-fur" d="M7 31 C9 18 20 15 32 15 C44 15 55 18 57 31 C56 38 52 44 46 49 C41 54 36 58 32 58 C28 58 23 54 18 49 C12 44 8 38 7 31 Z"/>
  <path class="fx-white" d="M8 33 C15 33 22 36 26 43 C28 47 30 50 32 50 C34 50 36 47 38 43 C42 36 49 33 56 33 C54 40 50 45 46 49 C41 54 36 58 32 58 C28 58 23 54 18 49 C14 45 10 40 8 33 Z"/>
  <path class="fx-line" fill="none" d="M7 31 C9 18 20 15 32 15 C44 15 55 18 57 31 C56 38 52 44 46 49 C41 54 36 58 32 58 C28 58 23 54 18 49 C12 44 8 38 7 31 Z"/>
  <path class="fx-brow" d="M18 27 L27 29.6 M46 27 L37 29.6"/>
  <g class="fx-eyes"><ellipse class="fx-ink" cx="24" cy="35.5" rx="3.4" ry="4"/><ellipse class="fx-ink" cx="40" cy="35.5" rx="3.4" ry="4"/>
    <circle class="fx-white" cx="25.3" cy="34" r="1.15"/><circle class="fx-white" cx="41.3" cy="34" r="1.15"/></g>
  <path class="fx-ink" d="M28.5 45.5 Q32 43 35.5 45.5 Q33.6 49.2 32 49.2 Q30.4 49.2 28.5 45.5 Z"/>
  <path class="fx-smile" d="M32 49.5 Q33.2 52.6 36.8 51.6"/>`;

const FOX_BODY = `
  <path class="fx-tail fx-fur fx-line" d="M86 122 C110 118 120 92 106 74 C104 92 96 104 80 108 Z"/>
  <path class="fx-tail fx-white" d="M106 74 C113 82 113 94 109.5 101 C106 93 104.5 83 106 74 Z"/>
  <path class="fx-jacket fx-line" d="M46 68 C36 70 30 80 29 96 L28 130 L96 130 L95 96 C94 80 88 70 78 68 Z"/>
  <path class="fx-white" d="M51 67 L62 86 L73 67 Z"/>
  <path class="fx-seam" d="M51 67 L62 86 L73 67 M62 86 L62 130"/>
  <path class="fx-cord" d="M52 70 Q62 99 72 70"/>
  <g class="fx-whistle fx-whistle-body"><rect class="fx-metal" x="57" y="86" width="11" height="6.5" rx="3"/><circle class="fx-metal" cx="59" cy="92" r="2.8"/></g>
  <g class="fx-board"><rect class="fx-ink" x="58" y="98" width="46" height="30" rx="4"/><rect class="fx-pitch" x="61" y="101" width="40" height="24" rx="2"/>
    <path class="fx-chalk" d="M81 101 V125 M65.5 106 l4 4 m0 -4 l-4 4 M70 117 Q80 108 92 113"/><circle class="fx-chalk" cx="81" cy="113" r="4"/>
    <circle class="fx-chalk" cx="95" cy="118" r="2.6"/></g>
  <ellipse class="fx-fur fx-line" cx="61" cy="104" rx="6.5" ry="5.2"/>
  <ellipse class="fx-fur fx-line" cx="101" cy="108" rx="6" ry="5"/>
  <g transform="translate(22 -3) scale(1.25)">${FOX_HEAD}</g>`;

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
