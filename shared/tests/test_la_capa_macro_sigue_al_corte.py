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
