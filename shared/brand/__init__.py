"""Marca SDQ·MIP — la ÚNICA fuente de la paleta y del símbolo, para todo lo que imprime.

**Por qué existe.** La marca vivía copiada. La paleta estaba declarada cuatro veces (el
renderizador PDF genérico, el Word, los gráficos y el PDF de banca) y el símbolo Arco,
otras cuatro (el componente del sidebar, el favicon del `index.html`, el snippet del
sistema de diseño y el PNG de los informes). Copiar no es un riesgo teórico: para cuando
se auditó, la aplicación estaba en azul ``#1E6FFF`` y los informes en ``#1A365D`` +
``#2B6CB0``, y el símbolo circulaba en TRES geometrías distintas — una de ellas con el
punto de señal fusionado contra el terminal del arco, que borra la metáfora del medidor.

Acá vive una sola definición y un test estructural verifica que nadie declare la suya
(``shared/brand/tests/``). Es la cura que la doctrina del repo pide cuando un defecto se
repite entre motores: un test que lee el código, no una lección escrita.

**Qué NO hace.** No dibuja nada ni conoce reportlab, python-docx ni matplotlib: sirve
constantes. Cada renderizador las convierte a su propio tipo de color. Y no conoce ningún
módulo de sector — es transversal, como manda la arquitectura.

**Espejo del frontend.** Los valores son los mismos de ``frontend/src/index.css`` (tema
claro, dirección «Claro & Vivo»). Un cambio de token se hace en los dos lados o el test
de paridad falla.
"""
from shared.brand.mark import (
    ARCO_ACCENT,
    ARCO_ARC_PATH,
    ARCO_ARC_RADIUS,
    ARCO_ARC_WIDTH,
    ARCO_CORNER_RADIUS,
    ARCO_DOT_CY,
    ARCO_DOT_R,
    ARCO_VIEWBOX,
    arco_metrics,
    arco_svg,
)
from shared.brand.tokens import (
    ACCENT,
    ACCENT_HOVER,
    ACCENT_INK,
    ACCENT_ON_DARK,
    ACCENT_SOFT,
    ALERT,
    ALERT_INK,
    ALERT_SOFT,
    BODY,
    BODY_ON_DARK,
    BORDER,
    BORDER_STRONG,
    CANVAS,
    FAINT,
    GRID,
    INK,
    MUTED,
    OK,
    OK_SOFT,
    SERIES,
    SURFACE,
    SURFACE_2,
    TEAL,
    TEAL_INK,
    TEAL_SOFT,
    WARN,
    WARN_SOFT,
    WHITE,
)

__all__ = [
    "ACCENT", "ACCENT_HOVER", "ACCENT_INK", "ACCENT_ON_DARK", "ACCENT_SOFT",
    "ALERT", "ALERT_INK", "ALERT_SOFT", "BODY", "BODY_ON_DARK", "BORDER", "BORDER_STRONG", "CANVAS", "FAINT", "GRID", "INK", "MUTED",
    "OK", "OK_SOFT", "SERIES", "SURFACE", "SURFACE_2", "TEAL", "TEAL_INK",
    "TEAL_SOFT",
    "WARN", "WARN_SOFT", "WHITE",
    "ARCO_ACCENT", "ARCO_ARC_PATH", "ARCO_ARC_RADIUS", "ARCO_ARC_WIDTH",
    "ARCO_CORNER_RADIUS", "ARCO_DOT_CY", "ARCO_DOT_R", "ARCO_VIEWBOX",
    "arco_metrics", "arco_svg",
]
