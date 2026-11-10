"""Genera los SVG de documentación del paso 1, sin modificar la aplicación ni consultar APIs."""

import re
from html import escape
from pathlib import Path
from textwrap import wrap

ROOT = Path(__file__).resolve().parent
DESTINATIONS = ["Hoy", "Partidos", "Seguimiento", "Explorar", "Más"]
VIEWS = {"hoy": "Hoy", "hoy-atrasado": "Hoy", "partidos": "Partidos", "ficha": "Partido", "mas": "Más"}


class Wireframe:
    def __init__(self, view: str, width: int, theme: str):
        self.width, self.mobile = width, width == 390
        self.height = (1122 if view == "ficha" else 1012 if view.startswith("hoy") else 964) if self.mobile else 900
        self.warning = view == "hoy-atrasado"
        self.parts: list[str] = []
        colors = ({"bg": "#f4f4f3", "card": "#ffffff", "line": "#b8bab9", "text": "#202522",
                   "muted": "#555e58", "soft": "#e8eae7", "active": "#263a30", "on": "#ffffff",
                   "warning": "#fff3d6", "warning-text": "#5c3500", "value": "#e1efe5", "value-text": "#205333"}
                  if theme == "claro" else
                  {"bg": "#111613", "card": "#1d2520", "line": "#6b766e", "text": "#f0f3ef",
                   "muted": "#b5bfb6", "soft": "#303c33", "active": "#dce6dd", "on": "#172019",
                   "warning": "#382b15", "warning-text": "#ffe0a0", "value": "#213c2b", "value-text": "#c1e8cd"})
        tokens = ";".join(f"--{key}:{value}" for key, value in colors.items())
        self.parts.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{self.height}" '
            f'viewBox="0 0 {width} {self.height}" style="{tokens}" role="img" aria-labelledby="title desc">'
            f'<title id="title">Wireframe de {VIEWS[view]}, {width} px, tema {theme}</title>'
            '<desc id="desc">Propuesta de estructura para revisión. Los corchetes indican contenido del backend; '
            'no son estadísticas ni partidos reales. No es una implementación de la aplicación.</desc>'
            '<style>text{font-family:Arial,sans-serif;fill:var(--text)}'
            '.box{fill:var(--card);stroke:var(--line);stroke-width:1}'
            '.soft{fill:var(--soft)}.muted{fill:var(--muted)}'
            '.active{fill:var(--active)}.on{fill:var(--on)}</style>'
            '<rect width="100%" height="100%" fill="var(--bg)"/>'
        )
        active = "Partidos" if view == "ficha" else VIEWS[view]
        if self.mobile:
            self.text(16, 20, "Fútbol ML", 13, bold=True)
            self.text(16, 48, VIEWS[view], 25, bold=True)
            subtitle = "Partidos, probabilidades y precio justo" if view == "partidos" else "Fútbol y análisis en papel"
            self.text(16, 73, "[Fecha local]" if view.startswith("hoy") else subtitle, 14, muted=True)
            self.button(16, 88, 173, "Preferencias", size=14)
            self.button(201, 88, 173, "Asistente", size=14)
            nav_y = self.height - 88
            self.box(0, nav_y, 390, 88, radius=0)
            for index, label in enumerate(DESTINATIONS):
                x = index * 78
                if label == active:
                    self.box(x + 4, nav_y + 9, 70, 56, cls="active", stroke=False)
                self.text(x + 39, nav_y + 32, ("○", "▤", "✓", "◇", "···")[index], 19,
                          center=True, cls="on" if label == active else "")
                self.text(x + 39, nav_y + 55, label, 11.5, center=True, cls="on" if label == active else "")
            self.text(195, self.height - 6, "Área segura del dispositivo", 10, center=True, muted=True)
            self.x, self.w = 16, 358
            self.parts.append('<g transform="translate(0,64)">')
        else:
            self.box(0, 0, 220, 900, radius=0)
            self.text(24, 44, "Fútbol ML", 23, bold=True)
            self.text(24, 70, "Análisis de fútbol", 14, muted=True)
            for index, label in enumerate(DESTINATIONS):
                y = 118 + index * 64
                self.button(16, y, 188, label, active=label == active, align_left=True)
            self.text(24, 831, "Seguimiento en papel", 13, muted=True)
            self.text(24, 855, "Metodología en Más", 13, muted=True)
            self.text(252, 49, VIEWS[view], 28, bold=True)
            subtitle = ("Partidos, probabilidades y precio justo" if view == "partidos"
                        else "Fútbol y análisis con contexto")
            self.text(252, 80, "[Fecha local]" if view.startswith("hoy") else subtitle, 15, muted=True)
            self.button(1124, 25, 148, "Preferencias")
            self.button(1284, 25, 124, "Asistente")
            self.x, self.w = 252, 1156
        self.status(compact=not view.startswith("hoy"))

    def box(self, x, y, w, h, radius=10, cls="box", stroke=True):
        stroke_attribute = "" if stroke else ' stroke="none"'
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" '
                          f'class="{cls}"{stroke_attribute}/>')

    def text(self, x, y, value, size=16, bold=False, muted=False, center=False, cls=""):
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" '
                          f'font-weight="{700 if bold else 400}" '
                          f'text-anchor="{"middle" if center else "start"}" '
                          f'class="{cls or ("muted" if muted else "")}">{escape(value)}</text>')

    def paragraph(self, x, y, value, width, size=16, muted=True):
        lines = wrap(value, width=max(10, int(width / (size * 0.54))))
        for index, line in enumerate(lines):
            self.text(x, y + index * (size + 6), line, size, muted=muted)

    def button(self, x, y, w, label, active=False, align_left=False, size=15):
        self.box(x, y, w, 44, cls="active" if active else "box", stroke=not active)
        self.text(x + 16 if align_left else x + w / 2, y + 28, label, size,
                  center=not align_left, cls="on" if active else "", bold=active)

    def status(self, compact=False):
        x, w = self.x, self.w
        if compact and not self.warning:
            self.text(x + 4, 113 if self.mobile else 139,
                      "Datos [fecha] · Asistente [estado] · [versión]" if self.mobile else
                      "Datos: [actualización] · Asistente: [estado] · Modelo: [versión]", 13 if self.mobile else 15,
                      muted=True)
            return
        if self.mobile:
            height = 76 if compact else 100
            self.box(x, 88, w, height, cls="box" if not self.warning else "soft")
            if self.warning:
                self.parts.append(f'<rect x="{x}" y="88" width="{w}" height="100" rx="10" fill="var(--warning)"/>')
            self.text(x + 14, 114, "Datos sin actualizar desde [fecha]" if self.warning else
                      "Datos: [estado y actualización]", 15, bold=True)
            self.text(x + 14, 139, "Asistente: [disponibilidad]", 14, muted=True)
            if not compact:
                self.text(x + 14, 169, "Modelo: [versión]", 14, muted=True)
        else:
            self.box(x, 108, w, 76)
            if self.warning:
                self.parts.append(f'<rect x="{x}" y="108" width="{w}" height="76" rx="10" fill="var(--warning)"/>')
            self.text(x + 20, 139, "Datos sin actualizar desde [fecha]" if self.warning else
                      "Datos: [estado según última actualización]", 16, bold=True)
            self.text(x + 20, 164, "[Fecha y hora local del backend]", 14, muted=True)
            self.text(x + 550, 139, "Asistente: [disponibilidad]", 15)
            self.text(x + 550, 164, "Resumen: [plantilla o IA]", 14, muted=True)
            self.text(x + 960, 151, "[Versión del modelo]", 14, muted=True)

    def kpi(self, x, y, w, title, context, value="[total]"):
        self.box(x, y, w, 96)
        self.text(x + 14, y + 25, title, 14, bold=True)
        self.text(x + 14, y + 57, value, 25)
        self.text(x + 14, y + 81, context, 13, muted=True)

    def match(self, x, y, w, h=122, value=None):
        self.box(x, y, w, h)
        self.text(x + 14, y + 23, "[Liga] · [hora local] · [estado]", 14, muted=True)
        self.text(x + 14, y + 53, "Equipo local — Equipo visitante", 16, bold=True)
        self.text(x + 14, y + 81, "Local [dato] · Empate [dato] · Visita [dato]", 14)
        self.text(x + 14, y + 108, "Fuente: [origen]", 13, muted=True)
        self.text(x + w - 18, y + 108, "→", 18, center=True)
        if value is not None:
            self.parts.append(f'<rect x="{x + 14}" y="{y + 122}" width="{w - 110}" height="30" '
                              f'rx="6" fill="var(--{"value" if value else "soft"})"/>')
            self.text(x + 24, y + 142, "Con ventaja [+x%] · Pinnacle" if value else "Sin ventaja", 13, bold=True)
            self.text(x + w - 84, y + 142, "Semáforo", 12, muted=True)

    def hoy(self):
        x, w = self.x, self.w
        if self.mobile:
            self.box(x, 202, w, 112)
            self.text(x + 14, 230, "Tus equipos, primero", 18, bold=True)
            self.text(x + 14, 253, "Aún no elegiste favoritos.", 15, muted=True)
            self.button(x + 14, 263, 206, "Elegir mis equipos")
            self.kpi(x, 328, 173, "Partidos de hoy", "Todas las ligas · hoy")
            self.kpi(x + 185, 328, 173, "Con ventaja", "Pinnacle · hoy")
            self.box(x, 438, w, 106)
            self.text(x + 14, 465, "Tu resumen", 18, bold=True)
            self.text(x + 14, 492, "[Resumen obtenido del sistema]", 15)
            self.text(x + 14, 522, "[Modo de redacción del resumen]", 13, muted=True)
            self.text(x, 578, "Para revisar hoy", 20, bold=True)
            self.match(x, 594, w, 168, value=True)
            self.button(x, 782, w, "Ver todos los partidos")
        else:
            self.box(x, 208, 656, 126)
            self.text(x + 20, 241, "Tus equipos, primero", 20, bold=True)
            self.text(x + 20, 272, "Elige favoritos para priorizar sus próximos partidos.", 16, muted=True)
            self.button(x + 410, 281, 226, "Elegir mis equipos")
            self.kpi(x + 680, 208, 226, "Partidos de hoy", "Todas las ligas · hoy")
            self.kpi(x + 930, 208, 226, "Con ventaja de precio", "Pinnacle · hoy")
            self.box(x, 358, w, 116)
            self.text(x + 20, 392, "Tu resumen", 20, bold=True)
            self.text(x + 20, 423, "[Resumen obtenido del sistema: favoritos y oportunidades, cuando existan]", 16)
            self.text(x + 20, 452, "[Modo de redacción: plantilla o IA]", 14, muted=True)
            self.text(x, 520, "Para revisar hoy", 22, bold=True)
            self.button(x + w - 224, 490, 224, "Ver todos los partidos")
            self.match(x, 546, 566, 168, value=True)
            self.match(x + 590, 546, 566, 168, value=False)
            self.text(x + 14, 752, "(?) Qué significa tener ventaja · Ayuda contextual", 14, muted=True)

    def hoy_atrasado(self):
        x, w = self.x, self.w
        self.box(x, 202 if self.mobile else 208, w if self.mobile else 656, 112 if self.mobile else 126)
        self.text(x + 16, 232 if self.mobile else 242, "Tus equipos", 19, bold=True)
        self.text(x + 16, 262 if self.mobile else 274, "[Favoritos guardados]", 16, muted=True)
        self.text(x + 16, 292 if self.mobile else 308, "Actualización pendiente", 14, muted=True)
        for i, title in enumerate(("Partidos de hoy", "Con ventaja")):
            xx = x + 185 * i if self.mobile else x + 680 + 250 * i
            self.kpi(xx, 328 if self.mobile else 208, 173 if self.mobile else 226, title, "Hoy · en pausa", "—")
        y = 438 if self.mobile else 358
        self.box(x, y, w, 208)
        self.text(x + 16, y + 34, "Recomendaciones en pausa", 20, bold=True)
        self.paragraph(x + 16, y + 70, "No hay datos recientes. El resumen y las oportunidades se mostrarán "
                       "cuando exista información actualizada.", w - 32, 16)
        self.button(x + 16, y + 146, min(w - 32, 290), "Ver últimos resultados")

    def partidos(self):
        x, w = self.x, self.w
        if self.mobile:
            self.box(x, 180, w, 48)
            self.text(x + 14, 210, "Buscar equipo o competición…", 16, muted=True)
            self.button(x, 244, 92, "Hoy", active=True)
            self.button(x + 104, 244, 110, "Mañana")
            self.button(x + 226, 244, 132, "Calendario")
            self.text(x, 325, "Todas las ligas", 15)
            self.button(x + 244, 304, 114, "Filtros")
            for y in (364, 500, 636):
                self.match(x, y, w)
        else:
            self.box(x, 208, 558, 48)
            self.text(x + 16, 239, "Buscar equipo o competición…", 16, muted=True)
            self.button(x + 578, 210, 104, "Hoy", active=True)
            self.button(x + 694, 210, 118, "Mañana")
            self.button(x + 824, 210, 156, "Calendario")
            self.button(x + 992, 210, 164, "Liga: todas")
            self.text(x, 292, "Todas las ligas · [fecha seleccionada]", 16, muted=True)
            self.text(x + 490, 292, "Limpiar filtros", 15)
            for y in (316, 456, 596):
                self.match(x, y, 728)
            self.box(x + 752, 316, 404, 202)
            self.text(x + 772, 352, "Elige un partido", 20, bold=True)
            self.paragraph(x + 772, 388, "Consulta probabilidades, fuente y fecha. La forma, tabla y cuotas se "
                           "muestran al abrir el detalle.", 350)
            self.text(x + 772, 489, "Al volver se conserva tu lugar.", 15, muted=True)

    def ficha(self):
        x, w = self.x, self.w
        self.button(x, 180 if self.mobile else 208, 244, "← Volver a Partidos")
        y = 240 if self.mobile else 274
        self.box(x, y, w, 124)
        self.text(x + 18, y + 28, "[Competición] · [estado del partido]", 15, muted=True)
        self.text(x + 18, y + 62, "Equipo local — Equipo visitante", 18 if self.mobile else 25, bold=True)
        self.text(x + 18, y + 99, "[Fecha y hora local del encuentro]", 15, muted=True)
        y = 380 if self.mobile else 422
        left = w if self.mobile else 696
        self.box(x, y, left, 174)
        self.text(x + 16, y + 30, "Probabilidad de resultado (?)", 19, bold=True)
        for index, name in enumerate(("Local", "Empate", "Visita")):
            xx = x + left * (index + 0.5) / 3
            self.text(xx, y + 66, name, 15, center=True)
            self.text(xx, y + 102, "[dato]", 24, center=True)
        self.text(x + 16, y + 143, "[Fuente] · [vigencia de la predicción]", 14, muted=True)
        vx, vy, vw = (x, 570, w) if self.mobile else (x + 720, y, 436)
        self.box(vx, vy, vw, 276)
        self.text(vx + 16, vy + 30, "Ventaja de precio (?)", 19, bold=True)
        for dy, line in [(60, "Selección: [mercado y resultado]"),
                         (90, "Cuota: [dato] · Precio justo: [dato]"),
                         (120, "Ventaja: [+x%] · Pinnacle"), (150, "Monto sugerido: [dato]"),
                         (180, "¼ Kelly · máximo 2% por apuesta")]:
            self.text(vx + 16, vy + dy, line, 15)
        self.text(vx + 16, vy + 216, "Ver apuesta en Seguimiento →", 15, bold=True)
        self.text(vx + 16, vy + 245, "Solo si existe apuesta registrada", 13, muted=True)
        self.button(x, 862 if self.mobile else 620, w if self.mobile else 696, "Forma y tabla                       +")
        self.button(x if self.mobile else x + 720, 918 if self.mobile else 720,
                    w if self.mobile else 436, "Cuotas y modelo                    +")

    def mas(self):
        x, w = self.x, self.w
        rows = [
            ("Fiabilidad", "Métricas, pérdidas y límites del sistema"),
            ("Cómo funciona", "Fuentes, modelos y reglas de riesgo"),
            ("Preferencias", "Tus ligas y equipos favoritos"),
            ("Tema", "Claro / oscuro"),
            ("Asistente", "Disponibilidad: [estado del servicio]"),
        ]
        for index, (name, description) in enumerate(rows):
            if self.mobile:
                xx, yy, ww, hh = x, 184 + index * 112, w, 96
            else:
                xx, yy, ww, hh = x + (index % 2) * 590, 208 + (index // 2) * 174, 566, 150
            self.box(xx, yy, ww, hh)
            self.text(xx + 18, yy + 33, name, 19 if self.mobile else 22, bold=True)
            self.paragraph(xx + 18, yy + 62, description, ww - 60, 14 if self.mobile else 16)
            self.text(xx + ww - 25, yy + 35, "→", 21, center=True)
        if not self.mobile:
            self.text(x + 612, 602, "Todo está disponible también desde el móvil.", 17, muted=True)
            self.text(x + 612, 637, "Explorar reúne Simulador y Combinadas.", 17, muted=True)

    def write(self, filename):
        (ROOT / filename).write_text("\n".join([*self.parts, *(('</g>',) if self.mobile else ()), "</svg>\n"]),
                                     encoding="utf-8")


def main():
    for view in VIEWS:
        for width in (390, 1440):
            for theme in ("claro", "oscuro"):
                frame = Wireframe(view, width, theme)
                getattr(frame, view.replace("-", "_"))()
                frame.write(f"{view}-{width}-{theme}.svg")
    gallery = ROOT / "index.html"
    markup = gallery.read_text(encoding="utf-8")
    for view in VIEWS:
        frame = Wireframe(view, 390, "claro")
        markup = re.sub(rf'(src="{view}-390-claro.svg" width="390" height=")\d+(" alt=)',
                        rf'\g<1>{frame.height}\2', markup)
    gallery.write_text(markup, encoding="utf-8")


if __name__ == "__main__":
    main()
