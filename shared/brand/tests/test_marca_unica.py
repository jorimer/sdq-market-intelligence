"""REGLA ESTRUCTURAL: el símbolo Arco existe en UNA geometría, copiada verificadamente.

**El caso que la motivó.** El símbolo estaba escrito a mano en varios lugares —el componente
`ArcMark` del sidebar, el favicon de `frontend/index.html`, el snippet del sistema de diseño
y el PNG de los informes— y para cuando se auditó circulaban TRES construcciones distintas
en DOS azules:

- app y favicon: círculo con `stroke-dasharray`, hueco corto, **el punto fusionado contra
  el terminal del arco** — a tamaño de favicon se leía como una «C» manchada;
- PNG de informes: la construcción correcta (punto separado) pero en `#2B6CB0`;
- el dibujo con primitivas del PDF: un tercer conjunto de proporciones inventadas.

Ninguna de las tres estaba «mal» en su archivo. El defecto era que había tres.

**Por qué el test DESCUBRE las copias en vez de listarlas.** La primera versión de este
archivo traía una lista escrita a mano de tres rutas, y se le escapó una cuarta:
`frontend/DESIGN_SYSTEM.md`, el duplicado del sistema de diseño que vive dentro del
frontend, que siguió sirviendo el SVG retirado después de que todo lo demás se corrigiera.
Una lista a mano tiene exactamente el mismo defecto que el símbolo copiado: alguien la
tiene que acordar de actualizar. Así que acá se barre el repo y se marca como copia todo
archivo que dibuje un cuadrado redondeado de `rx="9"` en un `viewBox` de 32×32. Una quinta
copia entra sola al test el día que alguien la escriba.

**Por qué no basta con centralizar.** El frontend no puede importar Python y un favicon
tiene que ir embebido en el HTML, así que las copias son inevitables. Lo que sí se puede
evitar es que DIVERGAN: acá se comparan contra `shared/brand/mark.py`, que es la canónica.

**La regla.** Toda copia del símbolo reproduce la geometría canónica —el `path` del arco,
el grosor, el radio y la posición del punto, el radio del contenedor— y usa el azul de
marca (`#1E6FFF`) o la variable de tema (`var(--accent)`), nunca otro hex.
"""
import pathlib
import re
import urllib.parse

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

# La huella del símbolo: un contenedor redondeado de rx=9 en un lienzo de 32×32. Tolera
# comillas simples o dobles y espaciado libre, que es como varía entre JSX, HTML y Markdown.
_HUELLA_LIENZO = re.compile(r"""viewBox=["']0 0 32 32["']""")
_HUELLA_CONTENEDOR = re.compile(r"""<rect[^>]*\brx=["']9["']""")

# Dónde buscar. Se excluye lo generado y lo que documenta la retirada a propósito.
_RAICES = ("frontend", "design_handoff_sdqmip", "docs", "shared", "modules", "app")
_EXTENSIONES = (".tsx", ".ts", ".jsx", ".js", ".html", ".md", ".svg", ".py", ".css")
_EXCLUIDOS = ("node_modules", "/dist/", "/.vite/", "/__pycache__/", "/build/",
              # Este archivo describe la huella y las variantes retiradas: si se leyera a
              # sí mismo, la explicación fallaría el test que ella misma sostiene.
              "shared/brand/tests/")


def _leer(path: pathlib.Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix == ".html":
        # El favicon va percent-encoded en un data-URI: se decodifica para comparar.
        raw = urllib.parse.unquote(raw)
    return raw


# Un elemento `<svg>` completo. Es lo único que se compara: la prosa que lo rodea —el
# comentario del componente, la sección del sistema de diseño— EXPLICA la construcción
# retirada, y saber por qué se fue es lo que evita reintroducirla. Si el test leyera el
# archivo entero, cada explicación fallaría la regla que ella misma sostiene.
_SVG = re.compile(r"<svg\b.*?</svg>", re.S)


def _fragmentos_de_simbolo(texto: str) -> list:
    """Los elementos `<svg>` del archivo que dibujan el símbolo, sin su prosa."""
    return [m for m in _SVG.findall(texto) if _HUELLA_CONTENEDOR.search(m)]


def _copias() -> dict:
    """Descubre todo archivo del repo que dibuje el símbolo. `rel → fragmentos`."""
    encontradas = {}
    for raiz in _RAICES:
        base = RAIZ / raiz
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in _EXTENSIONES:
                continue
            rel = path.relative_to(RAIZ).as_posix()
            if any(x in f"/{rel}" for x in _EXCLUIDOS):
                continue
            texto = _leer(path)
            if not (_HUELLA_LIENZO.search(texto) and _HUELLA_CONTENEDOR.search(texto)):
                continue
            frags = _fragmentos_de_simbolo(texto)
            if frags:
                encontradas[rel] = frags
    return encontradas


COPIAS = _copias()

# Las copias que el repo tenía cuando se escribió la regla. Si el barrido devuelve MENOS,
# es que una se renombró o dejó de detectarse — y una copia que el test ya no mira es
# peor que una copia mal: pasa en verde. Que aparezcan más está bien; se verifican solas.
_COPIAS_CONOCIDAS = {
    "frontend/src/shared/layout/SidebarContent.tsx",
    "frontend/index.html",
    "frontend/DESIGN_SYSTEM.md",
    "design_handoff_sdqmip/DESIGN_SYSTEM.md",
    "docs/comercial/assets/arco.svg",
}


def test_el_barrido_sigue_encontrando_las_copias_conocidas():
    perdidas = _COPIAS_CONOCIDAS - set(COPIAS)
    assert not perdidas, (
        f"El barrido dejó de ver estas copias del símbolo: {sorted(perdidas)}.\n"
        "O se movieron —actualizá `_COPIAS_CONOCIDAS`— o la huella de detección se rompió, "
        "que es peor: el test pasaría en verde sin mirar nada."
    )


@pytest.mark.parametrize("rel", sorted(COPIAS))
def test_la_copia_reproduce_la_geometria_canonica(rel):
    texto = "\n".join(COPIAS[rel])
    faltan = [nombre for nombre, pieza in _PIEZAS.items() if pieza not in texto]
    assert not faltan, (
        f"{rel} no reproduce la geometría canónica del símbolo: falta {faltan}.\n"
        f"La canónica vive en shared/brand/mark.py; regenerá la copia desde `arco_svg()` "
        f"en vez de editarla a mano."
    )


@pytest.mark.parametrize("rel", sorted(COPIAS))
def test_la_copia_usa_el_azul_de_marca(rel):
    texto = "\n".join(COPIAS[rel])
    # El contenedor lleva el hex de marca, o la variable de tema si la copia es de la app.
    assert mark.ARCO_ACCENT in texto or "var(--accent)" in texto, (
        f"{rel} no usa el azul de marca del símbolo "
        f"(se esperaba {mark.ARCO_ACCENT} o var(--accent))."
    )
    assert "2B6CB0" not in texto.upper(), f"{rel} todavía usa el azul retirado #2B6CB0."


@pytest.mark.parametrize("rel", sorted(COPIAS))
def test_el_dashoffset_no_vuelve(rel):
    """La construcción punteada es la que fusionaba el punto: no puede reaparecer.

    Se verifica sobre los fragmentos del símbolo, no sobre el archivo entero:
    `stroke-dasharray` es legítimo en un gráfico (una línea de referencia discontinua).
    """
    texto = "\n".join(COPIAS[rel])
    assert "dashoffset" not in texto.lower(), (
        f"Volvió el arco dibujado con dasharray/dashoffset en {rel}. Esa construcción "
        "fusiona el punto de señal con el terminal del arco y borra la metáfora del "
        "medidor. Usá el `path` canónico."
    )


def test_el_sistema_de_diseno_no_se_bifurca():
    """Los dos `DESIGN_SYSTEM.md` son el mismo archivo, y tienen que seguir siéndolo.

    `design_handoff_sdqmip/` es el paquete de entrega y `frontend/` su copia instalada
    (así lo declara el README del handoff). Ya divergieron una vez: el arreglo del símbolo
    entró en uno y el otro siguió sirviendo el SVG retirado.
    """
    a = (RAIZ / "design_handoff_sdqmip/DESIGN_SYSTEM.md").read_text(encoding="utf-8")
    b = (RAIZ / "frontend/DESIGN_SYSTEM.md").read_text(encoding="utf-8")
    assert a == b, (
        "Los dos DESIGN_SYSTEM.md divergieron. El de `design_handoff_sdqmip/` es el "
        "original; copialo sobre `frontend/DESIGN_SYSTEM.md`."
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
