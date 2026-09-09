"""Quien cuenta contra el TECHO diario también registra en el LEDGER — o lo declara.

**El defecto, y por qué la lección escrita no alcanzó.** ``shared/llm/budget.record_usage``
incrementa un contador diario en Redis; ``shared/observability/llm_ledger.record_call``
guarda la fila consultable con su disparador. Son dos cosas distintas y el sitio que llama
solo a la primera existe para el corte de presupuesto y NO existe para «¿en qué se fue el
dinero?». Ya pasó con seis sitios —lo cuenta el docstring de ``account``— y volvió a pasar
con tres más en el motor de research: ruteo de dominios, pertinencia de entidad y relevancia
de pasajes gastaban sin dejar rastro atribuible.

La cura de un defecto que reincide entre motores no es una nota: es un lector de código que
lo exige. Este guard lee con ``ast`` y **resuelve el import**, no el nombre — ``shared/
data_api/quota.py`` tiene una función distinta que se llama igual, y un regex las
confundiría (y de paso taparía el caso real).

La salida correcta es ``llm_ledger.account``, que hace las dos en un solo sitio. Un módulo
que necesite separarlas se declara acá abajo con su motivo escrito.
"""
import ast
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]
PAQUETES = ("shared", "modules", "app")

#: Módulos que llaman a ``record_usage`` sin ``account`` a propósito, con el motivo.
#: Un módulo entra acá con una razón, no por conveniencia.
EXCEPCIONES = {
    "shared/llm/__init__.py":
        "solo la re-exporta.",
    "shared/observability/llm_ledger.py":
        "es `account`: la llama a propósito y agrega el registro al lado.",
    "shared/narrative/claude_engine.py":
        "separa a propósito: `_build_result` cuenta el gasto de la generación, y el "
        "registro se emite aparte para poder anotar también los HIT de caché —que no "
        "gastan— con su costo cero.",
}


def _ficheros():
    for paquete in PAQUETES:
        for f in (RAIZ / paquete).rglob("*.py"):
            rel = f.relative_to(RAIZ).as_posix()
            if "/tests/" in rel or rel.startswith("frontend/"):
                continue
            yield rel, f


def _importa_del_techo(arbol: ast.AST) -> bool:
    """¿Este módulo importa ``record_usage`` DEL contador de presupuesto?

    Se mira el módulo de origen: el mismo nombre existe en la cuota de la Data API y no
    tiene nada que ver con el gasto del modelo.
    """
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom) and nodo.module == "shared.llm.budget":
            if any(a.name == "record_usage" for a in nodo.names):
                return True
        if isinstance(nodo, ast.ImportFrom) and nodo.module == "shared.llm":
            if any(a.name == "record_usage" for a in nodo.names):
                return True
    return False


def _registra_en_el_ledger(arbol: ast.AST) -> bool:
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom) and (nodo.module or "").startswith(
                "shared.observability.llm_ledger"):
            if any(a.name in {"account", "record_call"} for a in nodo.names):
                return True
    return False


CANDIDATOS = sorted(rel for rel, _ in _ficheros())


def test_el_barrido_ENCUENTRA_ficheros():
    """Un barrido vacío pasa en verde sin comprobar nada, y el guard entero con él."""
    assert len(CANDIDATOS) >= 200, f"solo se leyeron {len(CANDIDATOS)} ficheros"


def test_el_barrido_VE_a_los_que_usan_el_techo():
    """Y si dejara de ver a los que sí lo usan, tampoco estaría comprobando nada."""
    usan = [rel for rel, f in _ficheros()
            if _importa_del_techo(ast.parse(f.read_text(encoding="utf-8")))]
    assert usan, "ningún fichero importa record_usage del presupuesto: el lector falló"


@pytest.mark.parametrize("rel", CANDIDATOS)
def test_quien_cuenta_contra_el_techo_tambien_deja_rastro_en_el_ledger(rel):
    arbol = ast.parse((RAIZ / rel).read_text(encoding="utf-8"))
    if not _importa_del_techo(arbol):
        return
    if rel in EXCEPCIONES:
        assert EXCEPCIONES[rel].strip(), f"{rel} está exceptuado sin motivo escrito"
        return
    assert _registra_en_el_ledger(arbol), (
        f"{rel} cuenta su gasto contra el techo diario (`shared.llm.budget.record_usage`) "
        f"pero no lo registra en el ledger. Su costo entra al corte de presupuesto y NO a "
        f"`GET /api/v1/operations/llm-spend`: no se puede atribuir a nadie. Usá "
        f"`shared.observability.llm_ledger.account`, que hace las dos, o declará el módulo "
        f"en EXCEPCIONES con el motivo.")


def test_una_excepcion_declarada_sigue_siendo_cierta():
    """Una excepción para un fichero que ya no usa el techo es ruido que envejece: si alguien
    la lee mañana creerá que ese módulo tiene un permiso especial que no necesita."""
    for rel in EXCEPCIONES:
        f = RAIZ / rel
        assert f.exists(), f"{rel} está en EXCEPCIONES y ya no existe"
        assert _importa_del_techo(ast.parse(f.read_text(encoding="utf-8"))), (
            f"{rel} está en EXCEPCIONES y ya no importa record_usage del presupuesto: "
            f"sacala de la lista")
