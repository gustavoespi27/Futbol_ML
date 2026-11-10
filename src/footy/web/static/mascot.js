/* El Míster: mascota del asistente. Un zorro DT («el zorro del banco»): ilustraciones originales del autor con el
   fondo quitado (scripts/prepare_mascot.py). Cada lugar del sitio usa su pose; si una pose aún no existe, la imagen
   cae a la pose base (full), así el sitio nunca muestra una imagen rota.
     face         cabeza: botón del chat, avatar, citas en estados vacíos
     full         cuerpo entero base
     chat-tablet  saludo del chat, mirando la tablet que sostiene ┐ se alternan: mira la tablet y luego al usuario
     chat-look    saludo del chat, mirando al usuario           ┘
     brief        con lentes, dando su análisis (resumen del día)
     alerts       dando un aviso (panel de avisos)
   Las animaciones mueven la imagen completa y solo corren sin «reducir movimiento». */

const MISTER_POSES = ["face", "full", "chat-tablet", "chat-look", "brief", "alerts"];
const misterSrc = (pose) => `/static/img/mister-${MISTER_POSES.includes(pose) ? pose : "full"}.png`;

function misterImg(pose, size, extra = "") {
  const fallback = pose === "face" || pose === "full" ? "" : ` onerror="this.onerror=null;this.src='${misterSrc("full")}'"`;
  return `<img class="mister mister-${pose} ${extra}" src="${misterSrc(pose)}" width="${size}" height="${size}"
    alt="" decoding="async"${fallback}>`;
}
const misterFace = (size = 32, extra = "") => misterImg("face", size, extra);
const misterFull = (size = 120, extra = "") => misterImg("full", size, extra);
// Saludo del chat: dos cuadros superpuestos que se alternan (mira la tablet, luego al usuario).
const misterChat = (size = 112) => `<span class="mister-duo mister-live" style="--duo:${size}px">
  ${misterImg("chat-tablet", size, "duo-a")}${misterImg("chat-look", size, "duo-b")}</span>`;
// Poses con efecto propio encima de la imagen: destello en los lentes (resumen) y ondas del silbato (avisos).
// Las posiciones son porcentajes de la ilustración (lentes y silbato), por eso escalan con el tamaño.
const MISTER_FX = {
  brief: '<svg class="fx-glint" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 0 14 10 24 12 14 14 12 24 10 14 0 12 10 10Z"/></svg>',
  alerts: `<svg class="fx-waves" viewBox="0 0 24 24" aria-hidden="true"><path d="M15 7a7 7 0 0 0 0 10"/>
    <path d="M11 4a11 11 0 0 0 0 16"/><path d="M7 1a15 15 0 0 0 0 22"/></svg>`,
};
const misterPose = (pose, size) => `<span class="mister-pose pose-${pose}" style="--pose:${size}px">
  ${misterImg(pose, size)}${MISTER_FX[pose] || ""}</span>`;
// Frase con el Míster para estados vacíos: el texto lo pone quien llama (siempre un hecho del sistema, sin cifras inventadas).
function misterQuote(text, size = 44) {
  return `<div class="mister-quote">${misterFace(size)}<p>${text}</p></div>`;
}
// El Míster «piensa» mientras el chat espera respuesta (ladea la cabeza).
function misterThinking(on) {
  document.querySelectorAll(".mister-live").forEach((el) => el.classList.toggle("is-thinking", on));
}

// Ranuras estáticas del HTML: <span data-mister="face|chat|brief|alerts|full" data-size="..."></span>
document.querySelectorAll("[data-mister]").forEach((slot) => {
  const pose = slot.dataset.mister, size = Number(slot.dataset.size) || 64;
  slot.innerHTML = pose === "chat" ? misterChat(size) : MISTER_FX[pose] ? misterPose(pose, size) : misterImg(pose, size);
});
