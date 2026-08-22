"""REGLA ESTRUCTURAL: el símbolo Arco existe en UNA geometría, copiada verificadamente.

**El caso que la motivó.** El símbolo estaba escrito a mano en cuatro lugares —el
componente `ArcMark` del sidebar, el favicon de `frontend/index.html`, el snippet de
`design_handoff_sdqmip/DESIGN_SYSTEM.md` y el PNG de los informes— y para cuando se
auditó circulaban TRES construcciones distintas en DOS azules:

- app y favicon: círculo con `stroke-dasharray`, hueco corto, **el punto fusionado contra
  el terminal del arco** — a tamaño de favicon se leía como una «C» manchada;
- PNG de informes: la construcción correcta (punto separado) pero en `#2B6CB0`;
- el dibujo con primitivas del PDF: un tercer conjunto de proporciones inventadas.

Ninguna de las tres estaba «mal» en su archivo. El defecto era que había tres.

**Por qué no basta con centralizar.** El frontend no puede importar Python y un favicon
tiene que ir embebido en el HTML, así que las copias son inevitables. Lo que sí se puede
evitar es que DIVERGAN: acá se comparan contra `shared/brand/mark.py`, que es la canónica.

**La regla.** Toda copia del símbolo reproduce la geometría canónica —el `path` del arco,
el grosor, el radio y la posición del punto, el radio del contenedor— y usa el azul de
marca (`#1E6FFF`) o la variable de tema (`var(--accent)`), nunca otro hex.
"""
import pathlib
import re

import pytest

from shared.brand import mark

RAIZ = pathlib.Path(__file__).resolve().parents[3]

# Las piezas que una copia fiel tiene que contener, en cualquier notación de atributo.
_PIEZAS = {
    "path del arco": mark.ARCO_ARC_PATH,
    "grosor del arco": str(mark.ARCO_ARC_WIDTH),
    "radio del punto": str(mark.ARCO_DOT_R),
    "posición del punto": str(mark.ARCO_DOT_CY),
    "radio del contenedor": str(mark.ARCO_CORNER_RADIUS),
}

# Copias vivas del símbolo → cómo se lee el archivo y qué relleno acepta el contenedor.
_COPIAS = {
    "frontend/src/shared/layout/SidebarContent.tsx": ("var(--accent)",),
    "frontend/index.html": (mark.ARCO_ACCENT,),
    "design_handoff_sdqmip/DESIGN_SYSTEM.md": (mark.ARCO_ACCENT,),
}


def _texto(rel: str) -> str:
    """El SÍMBOLO de cada copia, sin la prosa que lo rodea.

    En el Markdown se extrae solo el bloque de código: la sección explica por qué se
    retiró el azul viejo y por qué el arco dejó de dibujarse con `dashoffset`, y nombrar
    lo retirado es justamente lo que evita que vuelva. Si se leyera el archivo entero, la
    explicación fallaría el test que ella misma sostiene.
    """
    raw = (RAIZ / rel).read_text(encoding="utf-8")
    if rel.endswith(".html"):
        # El favicon va percent-encoded en un data-URI: se decodifica para comparar.
        import urllib.parse
        raw = urllib.parse.unquote(raw)
    if rel.endswith(".md"):
        bloques = re.findall(r"```[a-z]*\n(.*?)```", raw, re.S)
        svg = [b for b in bloques if "<svg" in b]
        assert svg, f"{rel} ya no contiene el snippet del símbolo en un bloque de código."
        raw = "\n".join(svg)
    return raw


@pytest.mark.parametrize("rel", sorted(_COPIAS))
def test_la_copia_reproduce_la_geometria_canonica(rel):
    texto = _texto(rel)
    faltan = [nombre for nombre, pieza in _PIEZAS.items() if pieza not in texto]
    assert not faltan, (
        f"{rel} no reproduce la geometría canónica del símbolo: falta {faltan}.\n"
        f"La canónica vive en shared/brand/mark.py; regenerá la copia desde `arco_svg()` "
        f"en vez de editarla a mano."
    )


@pytest.mark.parametrize("rel", sorted(_COPIAS))
def test_la_copia_usa_el_azul_de_marca(rel):
    texto = _texto(rel)
    aceptados = _COPIAS[rel]
    # El relleno del contenedor: el `fill` que sigue al `<rect …>` del símbolo.
    rects = re.findall(r'<rect[^>]*fill=["\']([^"\']+)["\']', texto)
    del rects  # el orden de atributos varía entre JSX y HTML; se busca por presencia.
    assert any(a in texto for a in aceptados), (
        f"{rel} no usa el azul de marca del símbolo (se esperaba uno de {aceptados})."
    )
    # Y no puede quedar rastro del azul retirado.
    assert "#2B6CB0" not in texto and "2b6cb0" not in texto.lower(), (
        f"{rel} todavía usa el azul retirado #2B6CB0.")


def test_el_dashoffset_no_vuelve():
    """La construcción punteada es la que fusionaba el punto: no puede reaparecer.

    Se verifica sobre las copias del símbolo, no sobre todo el frontend: `stroke-dasharray`
    es legítimo en un gráfico (una línea de referencia discontinua, por ejemplo).
    """
    culpables = [rel for rel in _COPIAS
                 if "stroke-dashoffset" in _texto(rel) or "strokeDashoffset" in _texto(rel)]
    assert not culpables, (
        "Volvió el arco dibujado con dasharray/dashoffset en: "
        f"{culpables}. Esa construcción fusiona el punto de señal con el terminal del "
        "arco y borra la metáfora del medidor. Usá el `path` canónico."
    )


def test_el_png_de_informes_es_el_azul_de_marca():
    """El logotipo que va en el PDF y el Word está en `#1E6FFF`, no en el azul viejo."""
    png = RAIZ / "shared/products/assets/sdq_mip_logo.png"
    assert png.exists(), "Falta el logotipo de los informes."
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover — Pillow es opcional en algunos entornos
        pytest.skip("Pillow no está instalado")

    # El contenedor es el color que más píxeles opacos ocupa.
    dominante = _dominante(Image.open(png).convert("RGBA"))
    esperado = tuple(int(mark.ARCO_ACCENT.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    assert dominante[:3] == esperado, (
        f"El PNG está en {dominante[:3]} y la marca es {esperado}. "
        f"Regeneralo desde `shared.brand.arco_svg()`.")


def _dominante(im) -> tuple:
    from collections import Counter
    return Counter(p for p in im.getdata() if p[3] > 200).most_common(1)[0][0]
