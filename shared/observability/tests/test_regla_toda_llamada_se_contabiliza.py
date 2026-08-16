"""REGLA ESTRUCTURAL: todo sitio que llame al modelo contabiliza su gasto.

**El caso que la motivó.** De quince sitios que llamaban al modelo, solo seis contaban su
gasto contra el techo diario. Los nueve que no lo hacían incluían la **visión** —la llamada
más cara de la plataforma, la que ya había costado dinero en relecturas de mazos—, la
extracción de PDF y las tres rutas del agente de investigación, agendado semanalmente.

La consecuencia no era solo un registro incompleto: ``LLM_DAILY_BUDGET_USD`` **no podía
cortar esas rutas nunca**, gastaran lo que gastaran, porque para el contador no existían.
El techo que parecía proteger a toda la plataforma protegía solo a la narrativa.

**Por qué un test y no una lección.** Este repo ya acumuló seis instancias de un guard
presente en un motor y ausente en otro, y la lección escrita no alcanzó ninguna de las
veces. Lo que sí funcionó fue leer el código con ``ast`` y exigir la regla.

**La regla.** Un módulo que contiene ``…messages.create(`` tiene que nombrar ``account``
—o ``record_usage``, para los que ya contaban antes de que existiera el registro—. Si un
sitio legítimamente no debe contabilizar, se declara en ``EXENTOS`` con su motivo escrito.
"""
import ast
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]

#: Formas de contabilizar. ``account`` hace las dos cosas (techo + registro atribuido);
#: ``record_usage`` es la anterior, que solo alimenta el techo — se acepta para no forzar
#: una migración masiva, pero lo nuevo debería usar ``account``.
_CONTABILIZA = ("account", "record_usage")

#: Sitios que llaman al modelo y NO contabilizan, con el motivo. Vacío a propósito: si
#: alguien agrega uno, tiene que escribir por qué.
EXENTOS: dict = {}

# `/.claude/` guarda los worktrees de las sesiones concurrentes: COPIAS del árbol, con los
# mismos archivos bajo otro prefijo. Sin excluirlas, este test denuncia nueve incumplimientos
# que son los mismos archivos ya conformes, y —peor— el veredicto pasa a depender de qué tenga
# checkouteado otra sesión en el disco de quien lo corre. Un gate estructural que falla por el
# estado local de otro deja de ser una señal y empieza a enseñar a ignorarlo.
_EXCLUIR = ("/tests/", "/.venv/", "/node_modules/", "/.claude/")


def _fuentes():
    for p in sorted(RAIZ.glob("**/*.py")):
        rel = str(p.relative_to(RAIZ))
        if any(x in f"/{rel}" for x in _EXCLUIR):
            continue
        yield rel, p


def _llama_al_modelo(arbol: ast.AST) -> bool:
    for n in ast.walk(arbol):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "create"
                and isinstance(n.func.value, ast.Attribute)
                and n.func.value.attr == "messages"):
            return True
    return False


def _nombres(arbol: ast.AST) -> set:
    return {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)
    }


def test_todo_sitio_que_llama_al_modelo_contabiliza_su_gasto():
    incumplen = []
    revisados = 0
    for rel, path in _fuentes():
        try:
            arbol = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        if not _llama_al_modelo(arbol):
            continue
        revisados += 1
        if rel in EXENTOS:
            continue
        if not (_nombres(arbol) & set(_CONTABILIZA)):
            incumplen.append(rel)

    assert revisados >= 10, (
        "el detector dejó de encontrar los sitios que llaman al modelo; se volvió "
        f"decorativo (encontró {revisados})"
    )
    assert not incumplen, (
        "Estos sitios llaman al modelo y NO contabilizan su gasto. No es solo un registro "
        "incompleto: su gasto tampoco cuenta contra LLM_DAILY_BUDGET_USD, así que el techo "
        "diario no puede cortarlos. Agregá `account(...)` tras la llamada, o declaralos en "
        "EXENTOS con su motivo:\n  " + "\n  ".join(incumplen)
    )


def test_la_exencion_exige_motivo_escrito():
    for sitio, motivo in EXENTOS.items():
        assert motivo and len(motivo) > 20, (
            f"{sitio} está exento sin un motivo que se sostenga: escribí por qué esa "
            "llamada no debe contar contra el presupuesto."
        )


def test_la_visio_y_la_extraccion_estan_cubiertas():
    """Los dos caros por unidad, fijados por nombre: son los que más duelen si se caen."""
    for rel in ("modules/brand_intel/ingest/pdf_vision.py",
                "shared/pdf/audited_extractor.py"):
        p = RAIZ / rel
        if not p.exists():
            pytest.skip(f"{rel} ya no existe")
        assert "account(" in p.read_text(encoding="utf-8"), rel
