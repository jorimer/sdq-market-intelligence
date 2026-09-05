"""Los clientes de la SIB viven en `shared/data`, y el shim es solo compatibilidad.

**Por qué se promovieron (T-VL-0).** Traen balance y resultados completos por entidad, y el
eje de valuación los necesita. La doctrina de la casa es que **un módulo no importa de otro**;
un valuador atado a `modules.banking_score` quedaría preso de los cambios de un motor que
responde otra pregunta —«qué tan sano está»— cuando el valuador responde «cuánto vale».

**Por qué el shim RE-EXPORTA y no reasigna `sys.modules`.** El alias de módulo era
tentador: hace que parchar el shim alcance a la implementación, sin tocar ningún test. Pero
mypy no lo atraviesa —ve un módulo que no define nada y marca `attr-defined` en cada import,
21 errores repartidos por ocho archivos ajenos—, y la alternativa costaba TRES líneas. Se
midió antes de elegir.

**El precio del re-export, y su guard.** Copia REFERENCIAS: `monkeypatch.setattr` sobre el
shim parcha la copia y la implementación real sigue intacta. El modo de falla es el peor que
hay — el parche "funciona", no tiene efecto, y el test pasa probando nada. Por eso hay un
test estructural de que NADIE parcha el shim: es lo que vuelve segura la re-exportación.
"""
import ast
import pathlib

import pytest

CLIENTES = ("sib_data_client", "sib_historical_client", "simbad_client")
_RAIZ = pathlib.Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("mod", CLIENTES)
def test_el_cliente_vive_en_shared_data(mod):
    assert (_RAIZ / "shared" / "data" / f"{mod}.py").exists()


@pytest.mark.parametrize("mod", CLIENTES)
def test_el_shim_reexporta_TODO_lo_que_el_repo_importa(mod):
    """El contrato del shim, medido: cada nombre que alguien importa por la ruta vieja tiene
    que estar. Una lista escrita a mano se queda corta justo en el que se agregó después, y
    el consumidor se entera con un ImportError."""
    import importlib

    shim = importlib.import_module(f"modules.banking_score.external.{mod}")
    faltan = sorted(n for n in _nombres_que_el_repo_importa(mod) if not hasattr(shim, n))
    assert not faltan, f"el shim de {mod} no re-exporta {faltan}"


def test_nadie_PARCHA_el_shim():
    """El guard que vuelve segura la re-exportación.

    Un shim que copia referencias no propaga un `monkeypatch.setattr`: el parche toca la
    copia, la implementación sigue intacta y el test pasa **probando nada**. Se parcha el
    módulo canónico, que es además donde vive la función.
    """
    culpables = {}
    for f in _fuentes(incluir_banking=True):
        try:
            arbol = ast.parse(f.read_text())
        except SyntaxError:
            continue
        alias = {a.asname or a.name.rsplit(".", 1)[-1]
                 for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom)
                 and n.module == "modules.banking_score.external"
                 for a in n.names if a.name in CLIENTES}
        if not alias:
            continue
        for n in ast.walk(arbol):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "setattr" and n.args
                    and isinstance(n.args[0], ast.Name) and n.args[0].id in alias):
                culpables.setdefault(str(f.relative_to(_RAIZ)), []).append(n.args[0].id)
    assert not culpables, (
        "estos archivos parchan el SHIM, que copia referencias: el parche no alcanza a la "
        f"implementación y el test pasa sin probar nada. Parchá `shared.data.*`: {culpables}")


@pytest.mark.parametrize("mod", CLIENTES)
def test_el_shim_no_tiene_codigo_propio(mod):
    """Un shim con lógica deja de ser un shim: se convierte en una segunda implementación
    que se desincroniza."""
    arbol = ast.parse((_RAIZ / "modules" / "banking_score" / "external" / f"{mod}.py").read_text())
    definiciones = [n for n in arbol.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    assert not definiciones, f"el shim de {mod} define {[d.name for d in definiciones]}"


def _importa_por_la_ruta_vieja(f: pathlib.Path) -> set:
    """Con `ast`, no regex: un paréntesis en un comentario trunca la lista de un guard y lo
    deja mirando la mitad del archivo sin que nada falle. Ya pasó en este repo."""
    try:
        arbol = ast.parse(f.read_text())
    except SyntaxError:
        return set()
    malos = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.ImportFrom) and n.module:
            if n.module.startswith("modules.banking_score.external"):
                hojas = {a.name for a in n.names} | {n.module.rsplit(".", 1)[-1]}
                malos |= hojas & set(CLIENTES)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith("modules.banking_score.external"):
                    hoja = a.name.rsplit(".", 1)[-1]
                    if hoja in CLIENTES:
                        malos.add(hoja)
    return malos


def _nombres_que_el_repo_importa(mod: str) -> set:
    """Leído con `ast` del repo entero, no de una lista."""
    nombres = set()
    for f in _fuentes(incluir_banking=True):
        try:
            arbol = ast.parse(f.read_text())
        except SyntaxError:
            continue
        for n in ast.walk(arbol):
            if isinstance(n, ast.ImportFrom) and n.module:
                if n.module.rsplit(".", 1)[-1] == mod:
                    nombres |= {a.name for a in n.names}
    return nombres


def _fuentes(incluir_banking: bool = False):
    for f in _RAIZ.rglob("*.py"):
        ps = f.relative_to(_RAIZ).parts
        if any(p in ps for p in (".venv", "node_modules", "__pycache__", ".claude")):
            continue
        # `banking_score` puede seguir usando su propia ruta histórica: el shim existe para
        # no tocarle nada, que es el sensor de este refactor.
        if not incluir_banking and ps[:2] == ("modules", "banking_score"):
            continue
        yield f


def test_el_barrido_encuentra_archivos():
    """Una aserción de ausencia pasa sola. Si el barrido queda vacío, el guard de abajo no
    prueba nada y nadie se entera."""
    assert sum(1 for _ in _fuentes()) > 100


def test_nadie_fuera_de_banking_score_usa_la_ruta_vieja():
    """El shim es compatibilidad para lo que ya estaba, no una puerta para código nuevo.

    Es la regla que T-VL-0 existe para habilitar: el eje de valuación —y cualquier módulo
    que venga— llega a los datos de la SIB por `shared.data`, nunca por `banking_score`.
    """
    culpables = {}
    for f in _fuentes():
        malos = _importa_por_la_ruta_vieja(f)
        if malos:
            culpables[str(f.relative_to(_RAIZ))] = sorted(malos)
    assert not culpables, (
        "estos archivos llegan a los clientes de la SIB por `modules.banking_score.external`. "
        f"Importalos de `shared.data`: {culpables}")
