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
        # El brazo pasa bajo el borde de la mejilla con margen: el contorno de la cara se queda en la cabeza.
        "head": [(0, 0), (229, 0), (229, 116), (166, 118), (150, 140), (132, 152), (92, 158), (52, 154), (38, 138),
                 (27, 128), (21, 119), (0, 111)],
        "tail": [(156, 116), (229, 116), (229, 206), (196, 218), (176, 206), (154, 160)],
        "arm": [(0, 114), (17, 121), (22, 129), (31, 137), (35, 152), (48, 157), (54, 170), (38, 178), (6, 172),
                (0, 152)],
        "neck": (64, 140, 122, 166),          # angosto: no asoma bajo las mejillas en reposo
        "fills": [(28, 150, 56, 178)],         # base del brazo: no queda hueco al mover el dedo
    },
    "alerts": {
        "source": "alerts",
        # El antebrazo cruza por delante de la mejilla: el brazo se recorta ajustado a su propio contorno (pata,
        # pulgar y los dos bordes del antebrazo) y la cabeza se queda con todo lo demás, incluido su borde derecho.
        "arm": [(139, 92), (146, 86), (156, 82), (166, 82), (175, 90), (175, 108), (169, 121), (153, 141), (139, 158),
                (128, 175), (113, 175), (106, 160), (108, 150), (127, 132), (144, 117), (139, 111), (137, 100)],
        "head": [(0, 0), (215, 0), (215, 60), (160, 62), (152, 82), (141, 92), (137, 100), (139, 111), (146, 117),
                 (130, 133), (112, 150), (110, 158), (70, 164), (30, 152), (0, 132)],
        "tail": [(150, 142), (158, 128), (166, 118), (215, 118), (215, 204), (176, 214), (164, 190), (150, 170)],
        "neck": (40, 134, 132, 168),
        "fills": [(112, 142, 150, 178)],       # hombro: no queda hueco al saludar
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
    # Prioridad brazo > cabeza > cola: cada capa pierde lo que ya tomó la anterior, así ningún trazo queda en dos
    # capas (al moverse se vería duplicado) ni se pierde (al moverse quedaría un hueco en la cara).
    parts: dict[str, Image.Image] = {}
    taken = Image.new("L", size, 0)
    for key in ("arm", "head", "tail"):
        if key in rig:
            parts[key] = ImageChops.subtract(mask(size, rig[key]), taken)
            taken = ImageChops.lighter(taken, parts[key])
    rest = Image.new("L", size, 255)
    for m in parts.values():
        rest = ImageChops.subtract(rest, m)
    body = layer(image, rest)
    neck = Image.new("RGBA", size, (0, 0, 0, 0))
    # Rellenos tras el cuerpo, recortados a lo que tapaban cabeza y brazo (y a lo pintado del dibujo): solo aparecen
    # en el hueco que dejan al girar, nunca sobre el fondo ni sobre la cola.
    fill = Image.new("L", size, 0)
    draw = ImageDraw.Draw(fill)
    for box in [rig["neck"], *rig.get("fills", [])]:
        draw.ellipse(box, fill=255)
    movable = Image.new("L", size, 0)
    for key in ("arm", "head"):
        if key in parts:
            movable = ImageChops.lighter(movable, parts[key])
    covered = ImageChops.multiply(ImageChops.multiply(fill, movable), image.getchannel("A"))   # nunca sobre el fondo
    neck.paste(fur_color(image), (0, 0), covered)
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
