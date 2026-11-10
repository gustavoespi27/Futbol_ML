/* El Míster: mascota del asistente, un zorro DT («el zorro del banco»), animado como títere de recortes.
   Cada pose viene cortada en capas del mismo lienzo (scripts/rig_mascot.py): cola, cuerpo, brazo y cabeza. El CSS las
   gira desde su articulación y la cabeza lleva párpados en SVG para parpadear. Coordenadas en píxeles de la pose
   (las mismas que en rig_mascot.py); los pivotes se pasan a % para que escalen con el tamaño.
     face    cabeza: botón del chat, avatar y citas (parpadea)
     chat    saludo del chat: lee la tablet y levanta la vista hacia el usuario; mientras piensa, sigue leyendo
     brief   resumen del día: con lentes, explica con el dedo en alto
     alerts  avisos: toca el silbato y saluda con la pata
   Las animaciones solo corren sin «reducir movimiento». */

const MISTER_RIGS = {
  face: { w: 256, h: 256, eyes: [[72, 167, 21, 25], [154, 167, 22, 25]] },
  chat: { w: 207, h: 234, tail: [148, 192], head: [70, 150], heads: ["head-tablet", "head"],
    eyes: [[44.5, 103, 13, 15.5], [95, 103, 13.5, 15.5]] },
  brief: { w: 229, h: 240, tail: [164, 192], arm: [44, 166], head: [90, 156], fx: "glint",
    eyes: [[62, 103, 11.5, 12], [112, 103, 12, 12]] },
  alerts: { w: 215, h: 241, tail: [166, 192], arm: [140, 168], head: [86, 160], fx: "waves",
    eyes: [[45, 98, 13.5, 15], [93, 98, 13.5, 15]] },
};
const MISTER_FX = {
  glint: '<path class="fx-glint" d="M128 80l2.6 9.4 9.4 2.6-9.4 2.6-2.6 9.4-2.6-9.4-9.4-2.6 9.4-2.6z"/>',
  waves: '<g class="fx-waves"><path d="M30 122a16 16 0 0 0 0 30"/><path d="M21 115a26 26 0 0 0 0 44"/><path d="M12 108a36 36 0 0 0 0 58"/></g>',
};
// URL versionadas (?v=) desde las precargas del HTML: tras regenerar las capas el navegador no usa copias viejas.
const MISTER_SRC = Object.fromEntries([...document.querySelectorAll('link[rel="preload"][as="image"]')]
  .map((link) => [new URL(link.href).pathname, link.href]));
const misterSrc = (path) => MISTER_SRC[path] || path;
const misterLayer = (name, part) => misterSrc(`/static/img/mister-${name}-${part}.png`);
const pivot = (rig, [x, y]) => `transform-origin:${(x / rig.w * 100).toFixed(1)}% ${(y / rig.h * 100).toFixed(1)}%`;

function misterRig(name, size, extra = "") {
  const rig = MISTER_RIGS[name], img = (src, cls, style = "") =>
    `<img class="rig-l ${cls}" src="${src}" alt="" decoding="async" draggable="false"${style ? ` style="${style}"` : ""}>`;
  // Párpado: elipse del color del pelaje que baja desde arriba; con el ojo cerrado aparece la curva de pestañas.
  const lids = `<svg class="rig-l rig-lids" viewBox="0 0 ${rig.w} ${rig.h}" aria-hidden="true">${rig.eyes.map(([cx, cy, rx, ry]) =>
    `<ellipse class="fx-lid" cx="${cx}" cy="${cy}" rx="${rx + 1}" ry="${ry + 1}"/><path class="fx-lash"
      d="M${cx - rx} ${cy + ry * .1}Q${cx} ${cy + ry * .55} ${cx + rx} ${cy + ry * .1}"
      style="stroke-width:${(rx / 6).toFixed(1)}"/>`).join("")}${MISTER_FX[rig.fx] || ""}</svg>`;
  const head = name === "face" ? img(misterSrc("/static/img/mister-face.png"), "rig-face") + lids
    : `<span class="rig-l rig-head" style="${pivot(rig, rig.head)}">${(rig.heads || ["head"]).map((part, i) =>
      img(misterLayer(name, part), `rig-${part}${i ? " rig-alt" : ""}`)).join("")}${lids}</span>`;
  const layers = name === "face" ? head : [
    img(misterLayer(name, "tail"), "rig-tail", pivot(rig, rig.tail)),
    img(misterLayer(name, "body"), "rig-body"),
    rig.arm ? img(misterLayer(name, "arm"), "rig-arm", pivot(rig, rig.arm)) : "",
    head,
  ].join("");
  return `<span class="mister mister-rig rig-${name} ${extra}" style="width:${size}px;aspect-ratio:${rig.w}/${rig.h}"
    aria-hidden="true">${layers}</span>`;
}

const misterFace = (size = 32, extra = "") => misterRig("face", size, extra);
// Frase con el Míster para estados vacíos: el texto lo pone quien llama (siempre un hecho del sistema, sin cifras inventadas).
function misterQuote(text, size = 44) {
  return `<div class="mister-quote">${misterFace(size)}<p>${text}</p></div>`;
}
// Mientras el chat espera respuesta, el Míster «piensa»: en el saludo sigue leyendo la tablet y la cabeza ladea.
function misterThinking(on) {
  document.querySelectorAll(".mister-live").forEach((el) => el.classList.toggle("is-thinking", on));
}

// Ranuras estáticas del HTML: <span data-mister="face|chat|brief|alerts" data-size="..." [data-live]></span>
document.querySelectorAll("[data-mister]").forEach((slot) => {
  const name = MISTER_RIGS[slot.dataset.mister] ? slot.dataset.mister : "face";
  slot.innerHTML = misterRig(name, Number(slot.dataset.size) || 64, slot.dataset.live !== undefined ? "mister-live" : "");
});
