/* El Míster: mascota del asistente. Un zorro DT («el zorro del banco»), dibujado en SVG propio a partir del
   diseño de referencia: cabeza de tres cuartos con hocico largo, orejas enormes, ojos de caricatura, cejas
   decididas y sonrisa confiada; silbato con cordón verde, tablet táctica y cinta verde en la cola.
   Dos variantes: cabeza (avatar, botón flotante, estados vacíos) y cuerpo entero (saludo del chat).
   Colores en clases .fx-* de styles.css; animaciones solo sin «reducir movimiento». */

// Cabeza mirando a la izquierda (viewBox 0 0 64 64). El orden importa: oreja trasera, cabeza, oreja delantera.
const FOX_HEAD_PATH = "M51 29 C51 18 43 11.5 32.5 11.5 C25 11.5 19 15 15.5 21 C12.5 26 8.5 30.5 4.5 34 " +
  "C2 36.5 3 40.8 6.5 41 C12.5 41.6 18 43.6 22.5 46.6 C27.5 49.8 34.5 50.4 40 48.6 L46.5 51 L44.8 46.8 L51.5 45.6 " +
  "L48 42.2 C50.6 38.6 51.6 34 51 29 Z";
const FOX_HEAD = `
  <g class="fx-ear fx-ear-r"><path class="fx-fur fx-line" d="M33 17 L45.5 -1.5 C49.5 7 51.5 16 50.5 26 Z"/>
    <path class="fx-inner" d="M37.5 17 L45 4.5 C47.4 10.5 48 16.5 47.3 22.5 Z"/></g>
  <path class="fx-fur" d="${FOX_HEAD_PATH}"/>
  <path class="fx-white" d="M4.2 36.6 C10.5 36.4 17 35.6 22.5 37.6 C28.5 39.8 35 41.8 44 41.2 L48 42.2 L51.5 45.6 L44.8 46.8 L46.5 51 L40 48.6 C34.5 50.4 27.5 49.8 22.5 46.6 C18 43.6 12.5 41.6 6.5 41 C4 40.8 3.2 38.6 4.2 36.6 Z"/>
  <path class="fx-line" fill="none" d="${FOX_HEAD_PATH}"/>
  <g class="fx-ear fx-ear-l"><path class="fx-fur fx-line" d="M16 22 C14.5 13 15.5 5 18.5 -1 C24.5 4.5 29 10 31 16 Z"/>
    <path class="fx-inner" d="M19 18.5 C18.2 12 18.8 7 20.2 3.5 C23.8 7.5 26.4 11 27.6 15 Z"/></g>
  <path class="fx-fur fx-line" d="M27 13 L28.5 6.5 L31.5 11.5 L34.5 6 L36 12.5"/>
  <g class="fx-eyes">
    <ellipse class="fx-sclera fx-line" cx="22" cy="28.5" rx="5" ry="6"/><ellipse class="fx-sclera fx-line" cx="34" cy="27.5" rx="5.6" ry="6.6"/>
    <circle class="fx-ink" cx="20.6" cy="29.6" r="3"/><circle class="fx-ink" cx="32.4" cy="28.8" r="3.3"/>
    <circle class="fx-white" cx="21.6" cy="28.4" r="1.1"/><circle class="fx-white" cx="33.5" cy="27.5" r="1.2"/></g>
  <path class="fx-brow" d="M15.5 20.5 Q21 19.6 26.5 23 M29.5 22.4 Q35 17.6 41 18.6"/>
  <ellipse class="fx-ink" cx="5" cy="37.4" rx="3.3" ry="2.6"/><circle class="fx-white" cx="4.2" cy="36.5" r=".8"/>
  <path class="fx-smile" d="M11.5 41.6 Q19.5 45.6 26.5 40.6 M25.2 39.4 Q27.4 40.2 26.5 42.4"/>`;
// Cordón verde y silbato bajo el hocico (solo en la cabeza suelta; el cuerpo entero lleva el suyo).
const FOX_CORD = `
  <path class="fx-cord" d="M26 46 Q33 62 44 47"/>
  <g class="fx-whistle"><rect class="fx-metal" x="28.5" y="54.5" width="9.5" height="5.6" rx="2.6"/><circle class="fx-metal" cx="30" cy="59.6" r="2.4"/></g>`;

// Cuerpo en cuatro patas (viewBox 0 0 140 112): pata delantera sobre la tablet táctica, cola en alto con cinta verde.
const FOX_BODY = `
  <ellipse class="fx-shadow" cx="72" cy="106" rx="56" ry="5"/>
  <g class="fx-tail">
    <path class="fx-fur fx-line" d="M96 74 C114 72 122 60 118 44 C116 36 120 28 126 24 C136 32 140 48 134 62 C128 76 112 84 98 82 Z"/>
    <path class="fx-white" d="M126 24 C131 22 136 21 139 22 C137 26 138 30 136 34 C134 31 130 29 127 30 C125.4 28 125.4 26 126 24 Z"/>
    <path class="fx-line" fill="none" d="M126 24 C131 22 136 21 139 22 C137 26 138 30 136 34 C138 40 138 48 134 62"/>
    <path class="fx-band fx-line" d="M117 40 L136 38 L137.5 45 L118 47.5 Z"/>
    <path class="fx-band fx-line" d="M135 41 L140 49 L135.5 52 L133 44 Z"/></g>
  <path class="fx-leg fx-fur fx-line" d="M86 78 L84 100 L94 100 L95 80 Z"/>
  <path class="fx-paw" d="M83.6 96 L94.3 96 L94 101 Q89 103 83.4 101 Z"/>
  <path class="fx-fur fx-line" d="M50 66 C52 54 68 52 86 55 C100 57 104 68 100 78 C96 86 82 88 70 86 C58 85 49 78 50 66 Z"/>
  <path class="fx-white" d="M56 76 C62 84 74 86 84 85 C76 80 66 78 56 76 Z"/>
  <path class="fx-leg fx-fur fx-line" d="M74 82 L73 101 L83 101 L84 82 Z"/>
  <path class="fx-paw" d="M72.8 97 L83.2 97 L83 102 Q78 104 72.6 102 Z"/>
  <path class="fx-leg fx-fur fx-line" d="M55 76 L56 101 L65 101 L66 80 Z"/>
  <path class="fx-paw" d="M55.8 97 L65.2 97 L65 102 Q60 104 55.6 102 Z"/>
  <g class="fx-board"><path class="fx-ink" d="M4 92 L42 82 L58 96 L18 108 Z"/><path class="fx-pitch" d="M9 92.4 L41.6 84 L53.4 95.2 L19.2 104.6 Z"/>
    <path class="fx-chalk" d="M25 88.2 L36.3 99.9 M14 93.4 l3.4 2.2 m0 -2.2 l-3.4 2.2 M18 100.5 Q27 95 37 97.5"/>
    <circle class="fx-chalk" cx="30.6" cy="94" r="3.4"/><circle class="fx-chalk" cx="44.5" cy="92.4" r="1.8"/></g>
  <path class="fx-leg fx-fur fx-line" d="M50 72 C46 80 42 86 38 90 L44 94 C50 88 56 82 60 76 Z"/>
  <path class="fx-paw" d="M37 89 C39 86.6 43 87 45.5 89.6 L43.4 94.4 Q39 94.6 36.4 92.6 Z"/>
  <g transform="translate(1 1) scale(1.3)">${FOX_HEAD}</g>
  <path class="fx-cord" d="M36 61 Q46 82 60 63"/>
  <g class="fx-whistle fx-whistle-body"><rect class="fx-metal" x="40" y="72" width="11" height="6.4" rx="3.2"/><circle class="fx-metal" cx="42" cy="78" r="2.8"/></g>`;

function misterFace(size = 32, extra = "") {
  return `<svg class="mister mister-face ${extra}" width="${size}" height="${size}" viewBox="0 -3 56 66" aria-hidden="true" focusable="false">${FOX_CORD}${FOX_HEAD}</svg>`;
}
function misterFull(size = 120, extra = "") {
  return `<svg class="mister mister-full ${extra}" width="${size}" height="${Math.round(size * 118 / 142)}" viewBox="0 -4 142 118" aria-hidden="true" focusable="false">${FOX_BODY}</svg>`;
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
