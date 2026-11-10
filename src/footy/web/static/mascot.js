/* El Míster: mascota del asistente. Un zorro DT («el zorro del banco»): ilustración original del autor,
   con el fondo quitado. Dos recortes: cabeza (avatar, botón flotante, resumen, estados vacíos) y cuerpo entero
   (saludo del chat). Las animaciones son de la imagen completa y solo sin «reducir movimiento». */

const MISTER_FACE_SRC = "/static/img/mister-face.png";
const MISTER_FULL_SRC = "/static/img/mister-full.png";

function misterFace(size = 32, extra = "") {
  return `<img class="mister mister-face ${extra}" src="${MISTER_FACE_SRC}" width="${size}" height="${size}" alt="" decoding="async">`;
}
function misterFull(size = 120, extra = "") {
  return `<img class="mister mister-full ${extra}" src="${MISTER_FULL_SRC}" width="${size}" height="${Math.round(size * 440 / 424)}" alt="" decoding="async">`;
}
// Frase con el Míster para estados vacíos: el texto lo pone quien llama (siempre un hecho del sistema, sin cifras inventadas).
function misterQuote(text, size = 44) {
  return `<div class="mister-quote">${misterFace(size)}<p>${text}</p></div>`;
}
// El Míster «piensa» mientras el chat espera respuesta (ladea la cabeza).
function misterThinking(on) {
  document.querySelectorAll(".mister-live").forEach((el) => el.classList.toggle("is-thinking", on));
}

// Ranuras estáticas del HTML: <span data-mister="face|full" data-size="..."></span>
document.querySelectorAll("[data-mister]").forEach((slot) => {
  const size = Number(slot.dataset.size) || undefined;
  slot.innerHTML = slot.dataset.mister === "full" ? misterFull(size) : misterFace(size);
});
