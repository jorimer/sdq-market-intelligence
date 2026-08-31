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
