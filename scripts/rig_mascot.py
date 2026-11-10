"""Corta las poses del Míster en capas para animarlas como recortes (cabeza, cuerpo, cola y brazo).

Cada capa conserva el lienzo completo de la pose, así se apilan sin cálculos de posición; el navegador las rota
desde su articulación (pivotes en static/mascot.js, mismas coordenadas en píxeles que aquí).
Detrás de la cabeza se pinta un cuello del color del pelaje para que al girar no quede un hueco.

Uso (después de scripts/prepare_mascot.py, que deja las poses sin fondo en assets/mascot/):
    .venv\\Scripts\\python scripts/rig_mascot.py
"""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "src" / "footy" / "web" / "static" / "img"
SOURCES = ROOT / "assets" / "mascot"

# Polígonos en píxeles de cada pose (medidos sobre la imagen sin fondo). "neck": elipse de relleno bajo la cabeza.
RIGS = {
    "chat": {
        "source": "chat-look",
        "head": [(0, 0), (207, 0), (207, 112), (136, 116), (130, 138), (112, 150), (68, 153), (26, 146), (0, 128)],
        "tail": [(136, 112), (207, 112), (207, 214), (160, 216), (132, 196), (130, 150)],
        "neck": (24, 128, 120, 160),
        "extra_heads": {"head-tablet": "chat-tablet"},
    },
    "brief": {
        "source": "brief",
        "head": [(0, 0), (229, 0), (229, 116), (166, 118), (150, 140), (132, 152), (92, 158), (52, 152), (36, 134),
                 (28, 112), (0, 108)],
        "tail": [(156, 116), (229, 116), (229, 206), (196, 218), (176, 206), (154, 160)],
        "arm": [(0, 112), (26, 112), (34, 132), (48, 148), (52, 168), (38, 176), (6, 170), (0, 152)],
        "neck": (44, 132, 140, 166),
    },
    "alerts": {
        "source": "alerts",
        # La cabeza sigue el borde de la oreja y el contorno izquierdo del brazo, que cruza sobre la mejilla.
        "head": [(0, 0), (215, 0), (215, 40), (164, 46), (147, 86), (137, 94), (138, 112), (128, 128), (114, 148),
                 (110, 158), (70, 164), (30, 152), (0, 132)],
        "tail": [(152, 142), (160, 128), (166, 118), (215, 118), (215, 204), (176, 214), (164, 190), (152, 170)],
        "arm": [(138, 92), (150, 85), (161, 83), (173, 88), (175, 100), (166, 118), (157, 133), (148, 146), (141, 159),
                (136, 171), (118, 168), (115, 150), (129, 132), (139, 116), (136, 104)],
        "neck": (40, 134, 132, 168),
    },
}


def mask(size: tuple[int, int], polygon: list[tuple[int, int]]) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).polygon(polygon, fill=255)
    return m


def layer(image: Image.Image, keep: Image.Image) -> Image.Image:
    out = image.copy()
    out.putalpha(ImageChops.multiply(image.getchannel("A"), keep))
    return out


def fur_color(image: Image.Image) -> tuple[int, int, int, int]:
    """Naranja más frecuente de la pose: el relleno del cuello y los párpados usan el mismo tono."""
    counts: dict[tuple[int, int, int], int] = {}
    for r, g, b, a in image.get_flattened_data():
        if a > 250 and r > 200 and 70 < g < 140 and b < 60:
            key = (r // 8 * 8, g // 8 * 8, b // 8 * 8)
            counts[key] = counts.get(key, 0) + 1
    r, g, b = max(counts, key=counts.get)
    return (r + 4, g + 4, b + 4, 255)


def build(name: str, rig: dict) -> None:
    image = Image.open(SOURCES / f"{rig['source']}.png").convert("RGBA")
    size = image.size
    parts = {key: mask(size, rig[key]) for key in ("head", "tail", "arm") if key in rig}
    rest = Image.new("L", size, 255)
    for m in parts.values():
        rest = ImageChops.subtract(rest, m)
    body = layer(image, rest)
    neck = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(neck).ellipse(rig["neck"], fill=fur_color(image))
    body = Image.alpha_composite(neck, body)                 # el cuello queda detrás del cuerpo
    body.save(IMG / f"mister-{name}-body.png", optimize=True)
    for key, m in parts.items():
        layer(image, m).save(IMG / f"mister-{name}-{key}.png", optimize=True)
    for key, source in rig.get("extra_heads", {}).items():
        other = Image.open(SOURCES / f"{source}.png").convert("RGBA")
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        canvas.paste(other, (0, 0))
        layer(canvas, parts["head"]).save(IMG / f"mister-{name}-{key}.png", optimize=True)
    print(f"{name}: {size[0]}×{size[1]} · capas {', '.join(['body', *parts, *rig.get('extra_heads', {})])}"
          f" · pelaje {fur_color(image)[:3]}")


if __name__ == "__main__":
    for rig_name, rig_spec in RIGS.items():
        build(rig_name, rig_spec)
