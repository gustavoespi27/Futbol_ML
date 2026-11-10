"use strict";
/* Se modifican nodos de texto, nunca value, data-*, ids ni nombres de las peticiones. */
(function (root) {
  function translator(names) {
    const escaped = Object.keys(names).sort((a, b) => b.length - a.length)
      .map(s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const pattern = new RegExp(`(?<![\\p{L}\\p{N}_])(?:${escaped.join("|")})(?![\\p{L}\\p{N}_])`, "gu");
    return text => String(text).replace(pattern, name => names[name]);
  }
  if (typeof module !== "undefined" && module.exports) { module.exports = { translator }; return; }
  const display = translator(JSON.parse(document.getElementById("team-display-es").textContent));
  root.FootyTeamDisplay = display;
  function translate(node) {
    if (node.nodeType === 3) {
      if (node.parentElement?.closest("script,style,textarea,[contenteditable]")) return;
      const text = display(node.nodeValue);
      if (text !== node.nodeValue) node.nodeValue = text;
    } else if (node.nodeType === 1) {
      if (node.matches("script,style,textarea,[contenteditable]")) return;
      for (const child of node.childNodes) translate(child);
    }
  }
  translate(document.body);
  new MutationObserver(changes => {
    for (const change of changes) {
      if (change.type === "characterData") translate(change.target);
      else for (const node of change.addedNodes) translate(node);
    }
  }).observe(document.body, { childList: true, subtree: true, characterData: true });
})(typeof window !== "undefined" ? window : globalThis);
