r"""Prepara una pose del Míster (mascota): quita el fondo blanco y recorta. Después se corta en capas con
scripts/rig_mascot.py, que es lo que usa el dashboard para animarlo.

Uso:
    .venv\Scripts\python scripts/prepare_mascot.py imagen.png --pose chat-tablet
    .venv\Scripts\python scripts/prepare_mascot.py imagen.png --pose chat-look --face 6,0,152,158 --clear 138,124

Poses (fuentes en assets/mascot/<pose>.png, no se publican):
    chat-tablet  sosteniendo la tablet y mirándola (cabeza que lee)
    chat-look    misma pose, mirando hacia el usuario (cuerpo del chat y cabeza que mira)
    brief        con lentes, dando su análisis (resumen del día)
    alerts       tocando el silbato y saludando (avisos)
--face recorta la cabeza (izquierda,arriba,derecha,abajo en píxeles de la imagen ya recortada) y genera
static/img/mister-face.png de 256×256 con cuello desvanecido, para avatar, botón del chat y estados vacíos.
--clear borra lo que asome abajo a la derecha del recorte (x,y desde la esquina del recorte), p. ej. la cola.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "footy" / "web" / "static" / "img"
SOURCES = ROOT / "assets" / "mascot"
POSES = ("chat-tablet", "chat-look", "brief", "alerts")
SENTINEL = (255, 0, 255)


def remove_background(image: Image.Image, threshold: int = 60) -> Image.Image:
    """Inunda el blanco desde los bordes (el interior blanco queda protegido por el contorno del dibujo)."""
    rgb = image.convert("RGB")
    w, h = rgb.size
    for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1), (0, h // 2),
                 (w - 1, h // 2)]:
        if rgb.getpixel(seed) != SENTINEL and min(rgb.getpixel(seed)) > 200:
            ImageDraw.floodfill(rgb, seed, SENTINEL, thresh=threshold)
    out = rgb.convert("RGBA")
    px = out.load()
    for y in range(h):
        for x in range(w):
            if px[x, y][:3] == SENTINEL:
                px[x, y] = (0, 0, 0, 0)
    # Halo del antialias: píxeles casi blancos pegados al fondo pasan a semitransparentes.
    edge = out.getchannel("A").filter(ImageFilter.MinFilter(3))
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a and edge.getpixel((x, y)) == 0 and min(r, g, b) > 200:
                px[x, y] = (r, g, b, int(255 * (1 - (min(r, g, b) - 200) / 55)))
    return out.crop(out.getbbox())


def face_crop(image: Image.Image, box: tuple[int, int, int, int], clear: tuple[int, int] | None = None) -> Image.Image:
    """Cabeza cuadrada de 256 px; el borde inferior se desvanece en vez de cortar el cuello en seco."""
    crop = image.crop(box)
    fade = max(4, crop.height // 14)            # proporcional: en imágenes chicas no debe tapar la boca
    px = crop.load()
    if clear:
        for y in range(clear[1], crop.height):
            for x in range(clear[0], crop.width):
                px[x, y] = (0, 0, 0, 0)
    for y in range(max(0, crop.height - fade), crop.height):
        k = (crop.height - y) / fade
        for x in range(crop.width):
            r, g, b, a = px[x, y]
            px[x, y] = (r, g, b, int(a * k))
    side = max(crop.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(crop, ((side - crop.width) // 2, side - crop.height), crop)
    return square.resize((256, 256), Image.LANCZOS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", type=Path)
    parser.add_argument("--pose", choices=POSES, required=True)
    parser.add_argument("--face", help="recorte de la cabeza: izquierda,arriba,derecha,abajo")
    parser.add_argument("--clear", help="borra desde x,y hasta la esquina inferior derecha del recorte")
    args = parser.parse_args()
    figure = remove_background(Image.open(args.image))
    print(f"Recorte sin fondo: {figure.size[0]}×{figure.size[1]} px")
    if args.face:
        box = tuple(int(v) for v in args.face.split(","))
        if len(box) != 4:
            parser.error("--face necesita cuatro números: izquierda,arriba,derecha,abajo")
        clear = tuple(int(v) for v in args.clear.split(",")) if args.clear else None
        face_crop(figure, box, clear).save(OUT / "mister-face.png", optimize=True)
        print(f"Cabeza: {OUT / 'mister-face.png'}")
    target = SOURCES / f"{args.pose}.png"
    figure.save(target, optimize=True)
    print(f"Pose {args.pose}: {target} ({figure.size[0]}×{figure.size[1]})")


if __name__ == "__main__":
    main()
