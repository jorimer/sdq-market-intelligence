"""Tokens de color de la marca — dirección «Claro & Vivo», tema claro.

Espejo exacto de ``:root`` en ``frontend/src/index.css``. Los informes imprimen en claro
siempre (el papel no tiene tema oscuro), así que acá solo vive esa mitad; el tema oscuro
es una preocupación de la interfaz y se queda en el CSS.

**Cuándo usar cuál, para texto en acento.** ``ACCENT`` (#1E6FFF) sobre blanco da 4,40:1 de
contraste — por debajo del 4,5:1 que pide WCAG AA para texto normal. Por eso el acento
pinta RELLENOS (barras, filetes, fondos) y el texto en acento usa ``ACCENT_INK``
(#1551C0, 7,07:1). No es preferencia: es la razón por la que el token existe.
"""
from __future__ import annotations

# ── Superficies y tinta ──
CANVAS = "#F5F8FC"        # fondo de página / filas alternas
SURFACE = "#FFFFFF"       # tarjetas y paneles
SURFACE_2 = "#F1F5FB"     # fondo hundido (bloques de código, anexos)
INK = "#0A1A3A"           # títulos, cifras, cabeceras de tabla — 17,19:1 sobre blanco
BODY = "#43506B"          # texto corrido — 8,08:1
MUTED = "#76829C"         # subtítulos y leyendas (nunca texto corrido)
FAINT = "#9AA6BF"         # metadato terciario
BORDER = "#E7ECF3"        # filetes y bordes de tarjeta
BORDER_STRONG = "#D6DEEC"  # divisores y bordes de campo

# ── Acento y estado ──
ACCENT = "#1E6FFF"        # rellenos: barras, filetes, fondos. NO para texto sobre blanco
ACCENT_HOVER = "#1A60E0"
ACCENT_SOFT = "#EAF1FF"
ACCENT_INK = "#1551C0"    # texto en acento — 7,07:1 sobre blanco
TEAL = "#0F7E7E"          # acento secundario (segunda serie de datos)
TEAL_SOFT = "#E3F2F2"
OK = "#15875A"            # positivo / fuerte
OK_SOFT = "#E5F3EC"
WARN = "#B7791F"          # vigilar
WARN_SOFT = "#FBF1DD"
ALERT = "#C8392E"         # crítico / débil / valor negativo / estampa de muestra
ALERT_SOFT = "#FBEAE8"

# ── Variantes derivadas: texto sobre fondo suave y sobre banda oscura ──
# No están en `index.css` porque la app no tiene estos componentes (una nota con fondo
# teal, un encabezado de informe en banda oscura). Existen por CONTRASTE, con el número
# medido al lado: el token base no alcanza sobre su propio `*_SOFT`.
TEAL_INK = "#0B4A4A"      # texto sobre TEAL_SOFT — 8,72:1 (TEAL directo da 4,24:1)
ALERT_INK = "#8E2A22"     # texto sobre ALERT_SOFT — 7,20:1 (ALERT directo da 4,42:1)
# Sobre banda oscura (encabezado de informe) son los valores del tema oscuro del CSS.
ACCENT_ON_DARK = "#93BBFB"   # acento sobre INK — 8,79:1
BODY_ON_DARK = "#AEB9D2"     # texto secundario sobre INK — 8,73:1

# ── Datos ──
GRID = "#EAEFF6"          # rejilla de gráfico
SERIES = ("#1E6FFF", "#0F7E7E", "#7A5AF8", "#B7791F", "#E0729A", "#2BA8A8")

WHITE = "#FFFFFF"
