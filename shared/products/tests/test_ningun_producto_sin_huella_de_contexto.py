"""REGLA ESTRUCTURAL: ningún producto puede tener la huella de CONTEXTO vacía.

**El defecto que cierra.** `ProductReportCache` no tiene TTL, y su huella tiene tres partes:
el dato, la RECETA (prompts, modelo, `GUARD_VERSION`) y el CONTEXTO — lo que se le pasa al
modelo. La tercera se resuelve buscando `AI_CONTEXT_FILES` en el módulo del producto; sin ella
cae a `ai_context.py`, y si tampoco existe devuelve **la cadena vacía**.

Una huella vacía no falla, no avisa y no rompe ningún test: simplemente **un arreglo de lo que
el modelo lee deja de invalidar la caché**, y el informe sigue sirviendo el texto viejo
indefinidamente. Es el defecto que en agosto dejó a MAPFRE publicando «cuatro compañías
concentran el 87,1 %» —eran cuatro RAMOS— después de que la corrección estuviera desplegada.

Tres productos estaban así el 2026-08-27 y ninguno lo sabía:

* `banking_year_review` — lo construí yo y nunca declaré `AI_CONTEXT_FILES`. Ese día se
  invalidó por casualidad: alguien bumpeó `GUARD_VERSION`, que es parte de la RECETA.
* `macro` y `monetary_policy` — viven en `app/` y la función descartaba todo lo que no
  estuviera bajo `modules/`.

Se descubrió porque el dueño preguntó si había que regenerar los trimestres. Ninguna prueba lo
habría dicho: por eso existe ésta.
"""
from __future__ import annotations

import pytest


def _productos():
    import app.main  # noqa: F401 — registra los productos reales

    from shared.products.registry import PRODUCT_CATALOG, get_product
    for entrada in PRODUCT_CATALOG:
        producto = get_product(entrada.sector_key, None)
        if producto is not None:
            yield entrada.sector_key, type(producto).__module__


def test_el_barrido_encuentra_productos():
    """Prueba NEGATIVA: sin registro no hay productos, no hay infractores y el test pasa en
    verde sin haber mirado nada."""
    assert len(list(_productos())) >= 14


def test_NINGUN_producto_tiene_la_huella_de_contexto_vacia():
    from shared.products.assembler import _contexto_ia_version

    sin_huella = [k for k, mod in _productos() if not _contexto_ia_version(mod)]
    assert sin_huella == [], (
        f"Estos productos no tienen huella de CONTEXTO: {sin_huella}. Un arreglo de lo que el "
        "modelo lee no invalidará su caché —que no tiene TTL— y el informe seguirá sirviendo "
        "el texto viejo indefinidamente, sin error y sin aviso. Declará `AI_CONTEXT_FILES` en "
        "el módulo del producto con los archivos que arman su contexto.")


def test_dos_productos_del_MISMO_modulo_comparten_la_lista_declarada():
    """Banca tiene dos productos y una sola lista, en `ai_context_files.py`. Duplicarla es
    cómo una lista se desincroniza — el defecto de las etiquetas de tipo de entidad, que
    llegaron a tener dos formas del mismo estrato."""
    from modules.banking_score import products, products_year_review
    from modules.banking_score.ai_context_files import AI_CONTEXT_FILES

    assert products.AI_CONTEXT_FILES is AI_CONTEXT_FILES
    assert products_year_review.AI_CONTEXT_FILES is AI_CONTEXT_FILES


@pytest.mark.parametrize("clave", ["banking", "banking_year_review"])
def test_los_archivos_declarados_EXISTEN(clave):
    """Un archivo declarado que no existe se hashea como nada: la lista parece cubrirlo y no
    cubre. Es la familia «un binding a una serie inexistente no falla»."""
    from modules.banking_score.ai_context_files import AI_CONTEXT_FILES
    from shared.products.assembler import ruta_de_contexto

    # La resolución se pide al ENSAMBLADOR, no se reimplementa: una ruta que empieza en
    # `shared/` sale de la raíz del repo y el resto del módulo. Cuando este test resolvía por
    # su cuenta, admitir `shared/` en el ensamblador lo dejó buscando
    # `modules/banking_score/shared/...` y declaró ausente un archivo que sí estaba.
    faltan = [f for f in AI_CONTEXT_FILES
              if not ruta_de_contexto(f, "banking_score").is_file()]
    assert faltan == [], f"Declarados y ausentes: {faltan}"


# ── Y la huella tiene que cubrir el archivo donde vive la PROSA ─────────────────────


def _con_prosa_computada():
    """Productos que redactan su informe con CÓDIGO, no con el motor de IA."""
    import app.main  # noqa: F401

    from shared.products.registry import PRODUCT_CATALOG, get_product
    for entrada in PRODUCT_CATALOG:
        producto = get_product(entrada.sector_key, None)
        if producto is None:
            continue
        try:
            niveles = producto.product_manifest().levels.values()
        except Exception:  # noqa: BLE001 — un manifiesto roto lo cubre otro test
            continue
        if any(getattr(n, "prosa_computada", False) for n in niveles):
            yield entrada.sector_key, type(producto).__module__


def test_el_barrido_encuentra_productos_de_prosa_computada():
    """Prueba NEGATIVA: si el barrido no encuentra ninguno, el test de abajo pasa en verde
    sin haber mirado nada."""
    assert len(list(_con_prosa_computada())) >= 2


def test_la_huella_CUBRE_el_archivo_donde_vive_la_prosa():
    """Un producto de prosa computada NO tiene «contexto de IA»: su receta ES el código que
    redacta. Si ese archivo no entra en la huella, un arreglo de texto se despliega y la
    caché —que no tiene TTL— sigue sirviendo el texto viejo indefinidamente.

    **Medido antes de este test:** cambiar el texto de una sección de `macro_forecast` dejaba
    el fingerprint IDÉNTICO. Lo que hizo llegar el cambio a producción fue que, de paso, se
    agregó un campo al payload — o sea, suerte. Los dos productos de prosa computada estaban
    así y ninguno lo sabía; con dos instancias, la lección escrita no alcanza.
    """
    import pathlib

    from shared.products.assembler import archivos_de_contexto

    huerfanos = []
    for clave, mod in _con_prosa_computada():
        propio = pathlib.Path(__import__(mod, fromlist=["_"]).__file__ or "").resolve()
        cubiertos = {p.resolve() for p in archivos_de_contexto(mod)}
        if propio not in cubiertos:
            huerfanos.append(f"{clave} ({propio.name})")
    assert huerfanos == [], (
        f"La prosa de estos productos vive fuera de la huella de la caché: {huerfanos}. "
        "Un arreglo de su texto se despliega y el informe sigue sirviendo el viejo, sin "
        "error y sin aviso. Declaralo en `AI_CONTEXT_FILES` del propio módulo.")
