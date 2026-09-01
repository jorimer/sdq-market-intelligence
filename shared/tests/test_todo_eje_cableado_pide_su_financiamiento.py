"""Un eje cableado tiene DOS mitades: el dato y la plantilla que lo pide.

**La lección que lo motivó, medida en producción el 2026-08-31.** Se cableó
`construction_intel` con el perfil de su sector y funcionó a la primera EN EL DATO: el bloque
viajaba en el contexto. La prosa generada no lo usó ni una vez. El modelo hacía lo correcto —
su plantilla dice «Usa EXCLUSIVAMENTE las cifras del contexto (…)» y enumera, y el
financiamiento no estaba en esa lista.

Es la familia de «el cómputo existe y la superficie no lo pide», que en la misma sesión
apareció con el mapa sectorial servido en 1 de 4 tipos de informe. Acá la superficie es el
PROMPT, que no se contaba como superficie.

Este test recorre los ejes cableados y exige las dos mitades. Un eje nuevo que sume el bloque
al contexto y olvide su plantilla queda con el dato viajando sin usarse, y NADA falla: el
informe sale, más pobre y en silencio.
"""
import ast
import importlib
import inspect

import pytest

from shared.narrative.claude_engine import THIN_TEMPLATES

#: eje → (módulo de contexto, plantilla, slug del marco BCRD-17).
#: Al cablear un eje nuevo se agrega acá; el test de abajo comprueba que la lista no se quede
#: corta contra el código.
EJES_CABLEADOS = {
    "construction": ("modules.construction_intel.ai_context", "construction_outlook",
                     "construccion"),
    "energy": ("modules.energy_intel.ai_context", "energy_outlook", "energia"),
    "free_zones": ("modules.free_zones_intel.ai_context", "free_zones_outlook",
                   "zonas_francas"),
    "tourism": ("modules.tourism_intel.ai_context", "tourism_outlook", "turismo"),
}


def test_el_barrido_no_esta_vacio():
    """Un `@parametrize` sobre una lista vacía sale SKIPPED, no FAILED."""
    assert len(EJES_CABLEADOS) == 4


@pytest.mark.parametrize("eje", sorted(EJES_CABLEADOS))
def test_el_contexto_del_eje_INCLUYE_el_bloque(eje):
    mod_name, _plantilla, _slug = EJES_CABLEADOS[eje]
    mod = importlib.import_module(mod_name)
    arbol = ast.parse(inspect.getsource(mod))
    # Se exige la LLAMADA en el dict de retorno, no que el nombre aparezca en el texto: el
    # comentario que explica el arreglo lo menciona y un test de texto se satisfaría con eso.
    llamadas = [n for n in ast.walk(arbol) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == "_financiamiento"]
    assert llamadas, f"{eje}: el contexto no arma el bloque de financiamiento"


@pytest.mark.parametrize("eje", sorted(EJES_CABLEADOS))
def test_la_plantilla_del_eje_PIDE_el_bloque(eje):
    _mod, plantilla, slug = EJES_CABLEADOS[eje]
    texto = THIN_TEMPLATES[plantilla]
    for clave in (f"credito_del_sistema_al_sector_{slug}",
                  f"costo_laboral_del_sector_{slug}"):
        assert clave in texto, (
            f"{eje}: la plantilla no nombra «{clave}». El bloque viaja en el contexto y el "
            "modelo no lo usa, porque la enumeración de cifras permitidas lo deja afuera")


@pytest.mark.parametrize("eje", sorted(EJES_CABLEADOS))
def test_la_plantilla_manda_a_CITAR_la_fecha_de_la_capa(eje):
    """Son capas de otro período que el índice del eje. Sin la fecha, el modelo las fecha en
    el encabezado del informe."""
    _mod, plantilla, _slug = EJES_CABLEADOS[eje]
    assert "corte_de_esta_capa" in THIN_TEMPLATES[plantilla]


@pytest.mark.parametrize("eje", sorted(EJES_CABLEADOS))
def test_la_plantilla_NO_manda_a_declarar_la_ausencia(eje):
    """Decisión del dueño del 2026-08-31: lo que no se puede afirmar no se menciona."""
    _mod, plantilla, _slug = EJES_CABLEADOS[eje]
    assert "no las menciones ni digas que" in THIN_TEMPLATES[plantilla]


def test_la_LISTA_no_se_queda_corta_contra_el_codigo():
    """La prueba negativa del barrido: si alguien cablea un quinto eje y no lo agrega acá,
    los tests de arriba siguen en verde sobre los cuatro que sí conocen — y el nuevo queda
    sin vigilancia, que es exactamente el modo de falla que este archivo previene."""
    import pathlib
    raiz = pathlib.Path(__file__).resolve().parents[2]
    cableados = set()
    for ctx in sorted(raiz.glob("modules/*/ai_context.py")):
        if "contexto_de_financiamiento" in ctx.read_text(encoding="utf-8"):
            cableados.add(ctx.parent.name)
    declarados = {m.split(".")[1] for m, _p, _s in EJES_CABLEADOS.values()}
    faltan = cableados - declarados
    assert not faltan, (
        f"estos ejes arman el bloque y no están en EJES_CABLEADOS: {sorted(faltan)}. "
        "Su plantilla podría no pedirlo y nadie se enteraría")
