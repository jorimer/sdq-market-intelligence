"""Símbolo Arco — la geometría canónica del logotipo, en un solo lugar.

**Qué es.** Un arco abierto (la aguja de un medidor 0–100) y un punto separado (el dato,
la señal). Resume el producto: un medidor explicable es literalmente lo que la plataforma
emite.

**El punto va SEPARADO, y es la parte que se rompió.** La versión que circulaba en la
aplicación dibujaba el arco con ``stroke-dasharray``/``stroke-dashoffset`` sobre un
círculo completo, y el hueco quedaba tan corto que el punto se fundía contra el terminal
del arco: a tamaño de favicon se leía como una «C» con una mancha, no como un medidor con
su lectura. El PNG de los informes sí tenía la construcción correcta, pero en otro azul.
La canónica toma la geometría del PNG y el azul de la aplicación.

Por eso el arco se declara como un ``path`` con ángulos explícitos y no como un círculo
punteado: un ``dashoffset`` codifica el hueco de forma indirecta —y quien lo edite no
tiene cómo saber que está moviendo el punto de contacto—, mientras que dos extremos
declarados no se pueden desplazar sin querer.

El hueco superior abarca 90° (de −45° a +45° respecto del eje vertical) y el punto se
apoya en su centro.
"""
from __future__ import annotations

from shared.brand.tokens import ACCENT, WHITE

ARCO_VIEWBOX = "0 0 32 32"
ARCO_CORNER_RADIUS = 9          # radio del contenedor redondeado
ARCO_ARC_RADIUS = 7.0           # radio medio del arco
ARCO_ARC_WIDTH = 3.5            # grosor del trazo
ARCO_DOT_CY = 6.6               # centro del punto de señal (eje Y)
ARCO_DOT_R = 2.6                # radio del punto de señal
ARCO_ACCENT = ACCENT            # azul del contenedor en contexto estático

# Arco de 270° con extremos redondeados: abre arriba, centrado en el eje vertical.
# Los extremos salen de (16 ± 7·sen45°, 16 − 7·cos45°) = (20,95 / 11,05 , 11,05).
ARCO_ARC_PATH = "M20.95 11.05 A 7 7 0 1 1 11.05 11.05"


def arco_metrics(size: float) -> dict:
    """Las medidas del símbolo escaladas a un contenedor de lado ``size``.

    Existe para que un renderizador que dibuja con primitivas (el canvas de reportlab, por
    ejemplo) no vuelva a inventar las proporciones. Ángulos en grados, medidos desde el eje
    +X y en sentido antihorario, que es la convención de reportlab.
    """
    k = size / 32.0
    return {
        "corner_radius": ARCO_CORNER_RADIUS * k,
        "arc_radius": ARCO_ARC_RADIUS * k,
        "arc_width": ARCO_ARC_WIDTH * k,
        "dot_radius": ARCO_DOT_R * k,
        "dot_offset": (16.0 - ARCO_DOT_CY) * k,   # del centro hacia arriba
        "arc_start_deg": 135.0,                    # el hueco superior abarca 45°–135°
        "arc_extent_deg": 270.0,
    }


def arco_svg(*, size: int = 32, fill: str = ARCO_ACCENT, ink: str = WHITE,
             title: str | None = None) -> str:
    """El símbolo como SVG completo.

    ``fill`` acepta un hex o una variable CSS (``var(--accent)``) para que la interfaz
    lo resuelva por tema; los contextos estáticos —favicon, PNG de informes— pasan el
    hex de marca.
    """
    head = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{ARCO_VIEWBOX}" ' \
           f'width="{size}" height="{size}">'
    cap = f"<title>{title}</title>" if title else ""
    return (
        f'{head}{cap}'
        f'<rect width="32" height="32" rx="{ARCO_CORNER_RADIUS}" fill="{fill}"/>'
        f'<path d="{ARCO_ARC_PATH}" fill="none" stroke="{ink}" '
        f'stroke-width="{ARCO_ARC_WIDTH}" stroke-linecap="round"/>'
        f'<circle cx="16" cy="{ARCO_DOT_CY}" r="{ARCO_DOT_R}" fill="{ink}"/>'
        f'</svg>'
    )
