"""La capacidad de pago se lee al CORTE del documento, nunca a la fecha de descarga.

Por qué existe. `capacidad_de_pago` es una capa nacional que se sirve dentro de documentos
FECHADOS. Seguros la leía bien —al período del rating—; pensiones y política monetaria la
leían con `date.today()`, así que un informe con corte 2024 traía la inflación por quintil,
la informalidad y el piso de ingreso del día en que alguien lo descargó. Es la familia del
#992 —la frescura envejeciendo sola dentro de un documento fechado— pero al revés: no
envejece, se adelanta, y el documento afirma sobre su corte cosas que son de otro momento.

Política monetaria es el caso agudo: sirve una vista AS-OF explícita para decisiones
históricas y aun así pedía la capa macro de hoy.

Se comprueba en las TRES superficies. El helper es uno solo y vive en `shared/` justamente
para que arreglar dos no fuera hacer una tercera copia — un módulo no puede importar de otro.
"""
import ast
import inspect
from datetime import date

import pytest

from shared.capacidad_de_pago import corte_del_periodo


class TestElHelperLeeLoQueLosProductosSirven:

    @pytest.mark.parametrize("periodo,esperado", [
        ("2026-06-30", date(2026, 6, 30)),
        ("2026-06-30T00:00:00", date(2026, 6, 30)),
        ("2025-12", date(2025, 12, 28)),
        ("2024-02", date(2024, 2, 28)),          # febrero: el 28 es seguro siempre
        # El año suelto es el período de los productos ANUALES. Caía a HOY y un informe de
        # 2025 citaba inflación hasta julio de 2026 (producción, 2026-09-15).
        ("2025", date(2025, 12, 31)),
        ("2024", date(2024, 12, 31)),
    ])
    def test_los_formatos_que_los_productos_sellan(self, periodo, esperado):
        assert corte_del_periodo(periodo) == esperado

    @pytest.mark.parametrize("basura", [None, "", "—", "no-es-fecha", "2026-13"])
    def test_un_periodo_ilegible_cae_a_HOY_y_no_a_una_fecha_inventada(self, basura):
        """Una fecha falsa serviría contexto de un momento que el informe no describe."""
        assert corte_del_periodo(basura) == date.today()


_SUPERFICIES = {
    "seguros": ("modules.insurance_intel.products", "insurance"),
    "pensiones": ("modules.pension_intel.products", "pension"),
    "politica_monetaria": ("app.products_monetary_policy", "monetary_policy"),
}


@pytest.mark.parametrize("nombre", sorted(_SUPERFICIES))
def test_ninguna_superficie_pide_la_capa_macro_a_HOY(nombre):
    """Se lee con `ast` la llamada real, no el nombre en el texto: un test que buscara
    `today` en el fuente lo encontraría en el comentario que explica este arreglo."""
    import importlib
    mod = importlib.import_module(_SUPERFICIES[nombre][0])
    arbol = ast.parse(inspect.getsource(mod))

    llamadas = [n for n in ast.walk(arbol)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "capacidad_de_pago"]
    assert llamadas, f"{nombre} dejó de servir la capacidad de pago"

    for c in llamadas:
        corte = c.args[1]
        # Prohibido `date.today()` DIRECTO como corte. Como respaldo de un período ilegible
        # sí es legítimo —el helper mismo lo hace—, y por eso se mira el argumento y no si
        # la palabra aparece en algún lado del archivo.
        es_hoy_pelado = (isinstance(corte, ast.Call)
                         and isinstance(corte.func, ast.Attribute)
                         and corte.func.attr == "today")
        assert not es_hoy_pelado, (
            f"{nombre} lee la capa macro a la fecha de descarga: un documento fechado "
            "afirmaría sobre su corte cifras de otro momento")


def test_el_helper_es_UNO_solo_y_seguros_lo_DELEGA():
    """Tres copias del mismo cuerpo es como una se queda atrás — ya pasó hoy con un
    serializador. Seguros tenía el único correcto; ahora los tres comparten cuerpo."""
    from modules.insurance_intel import products as ins
    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(ins)))
              if isinstance(n, ast.FunctionDef) and n.name == "_corte_del_periodo")
    nombres = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "corte_del_periodo" in nombres, (
        "seguros volvió a tener su propia copia del helper")
    # Y sigue funcionando para sus llamadores.
    assert ins._corte_del_periodo("2025-12-31") == date(2025, 12, 31)


#: Toda superficie que sirve la capa macro dentro de un documento fechado. Se descubre con
#: `ast` y se contrasta contra esta lista: una superficie nueva que la llame sin estar acá
#: hace fallar el test, en vez de quedar fuera como quedaron los cinco ejes del #1042.
_TODAS_LAS_SUPERFICIES = {
    "app/products_monetary_policy.py", "modules/banking_score/products.py",
    "modules/banking_score/products_year_review.py", "modules/construction_intel/products.py",
    "modules/energy_intel/products.py", "modules/free_zones_intel/products.py",
    "modules/insurance_intel/products.py", "modules/pension_intel/products.py",
    "modules/social_dev/products.py", "modules/telecom_intel/products.py",
    "modules/tourism_intel/products.py",
}
_LECTURAS_FECHADAS = {"capacidad_de_pago", "holgura_donde_opera", "holgura_donde_presta",
                      "holgura_de_la_region"}


def _llamadas_a_la_capa(ruta):
    import pathlib
    arbol = ast.parse(pathlib.Path(ruta).read_text(encoding="utf-8"))
    return [n for n in ast.walk(arbol) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id in _LECTURAS_FECHADAS]


def test_el_barrido_ve_TODAS_las_superficies_que_leen_la_capa():
    import pathlib
    raiz = pathlib.Path(__file__).resolve().parents[2]
    halladas = set()
    for ruta in list(raiz.glob("modules/*/products*.py")) + list(raiz.glob("app/products_*.py")):
        if _llamadas_a_la_capa(ruta):
            halladas.add(str(ruta.relative_to(raiz)))
    assert halladas == _TODAS_LAS_SUPERFICIES, (
        f"superficies nuevas: {sorted(halladas - _TODAS_LAS_SUPERFICIES)} · "
        f"ya no la leen: {sorted(_TODAS_LAS_SUPERFICIES - halladas)}")


@pytest.mark.parametrize("ruta", sorted(_TODAS_LAS_SUPERFICIES))
def test_ninguna_superficie_lee_la_capa_a_HOY(ruta):
    import pathlib
    raiz = pathlib.Path(__file__).resolve().parents[2]
    for c in _llamadas_a_la_capa(raiz / ruta):
        corte = c.args[1] if len(c.args) > 1 else None
        es_hoy = (isinstance(corte, ast.Call) and isinstance(corte.func, ast.Attribute)
                  and corte.func.attr == "today")
        assert not es_hoy, f"{ruta}:{c.lineno} lee la capa macro a la fecha de descarga"
