"""Un runner que encola una tarea de Celery ESPERA su desenlace antes de devolver.

**El defecto que lo obligó.** El 2026-09-14, ``POST /api/v1/operations/tramites-registro-unico/run``
dejó ``phase='completado'`` y ``error=None`` en menos de un segundo, mientras la tarea
``social.tramites_registro_unico`` seguía varios minutos bajando ~710 fichas del catálogo.
``_run_tramites`` hacía ``.delay()`` y devolvía ``{"via": "worker", "task_id": ...}``; el
console lo registraba como completado y cualquier excepción del worker quedaba fuera de
``status.error``. El mismo archivo ya tenía el patrón correcto en ``_run_digepres_salud``:
la lección estaba escrita a veinte líneas y no alcanzó.

**Qué exige.** Para toda operación registrada con ``Operation(...)``, su runner —y lo que
el runner llama, siguiendo los imports hasta otros archivos— no puede hacer
``.delay()``/``.apply_async()``/``send_task()`` y soltar el resultado. Cuenta como esperar:

- pasar el ``AsyncResult`` a ``esperar_tarea`` (``shared.operations.worker``), o
- consultar en la misma función ``X.ready()`` y ``X.failed()`` (o ``X.get()``).

Un runner que tenga una razón para despachar y volver va a ``EXCEPCIONES`` con esa razón.

Se lee con ``ast``: la regla tiene que valer también para un módulo que no importa en el
entorno de test.
"""
import ast
import pathlib

_RAIZ = pathlib.Path(__file__).resolve().parents[3]
_EXCLUIDOS = {".venv", "node_modules", ".git", "__pycache__", "frontend", "tests", ".claude"}
_ENCOLAR = {"delay", "apply_async", "send_task"}
_ESPERADOR = "esperar_tarea"
_PROFUNDIDAD = 4

#: ``"archivo::runner"`` → por qué ese runner puede despachar y volver sin esperar.
EXCEPCIONES: dict[str, str] = {}


# ── Índice del árbol ────────────────────────────────────────────────────────────

def _indice() -> dict[str, ast.Module]:
    out = {}
    for p in sorted(_RAIZ.rglob("*.py")):
        rel = p.relative_to(_RAIZ)
        if _EXCLUIDOS & set(rel.parts):
            continue
        try:
            out[rel.as_posix()] = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):          # pragma: no cover - defensivo
            continue
    return out


def _archivo_de_modulo(modulo: str, indice) -> str | None:
    base = modulo.replace(".", "/")
    for cand in (f"{base}.py", f"{base}/__init__.py"):
        if cand in indice:
            return cand
    return None


def _def_de_nivel_superior(archivo: str, nombre: str, indice):
    for n in indice[archivo].body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nombre:
            return n
    return None


def _importados(archivo: str, indice) -> tuple[dict, dict]:
    """(nombre → (módulo, nombre original), alias → módulo) de TODO import del archivo,
    incluidos los que viven dentro de funciones — el patrón del repo es importar tarde."""
    nombres, modulos = {}, {}
    for n in ast.walk(indice[archivo]):
        if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            for a in n.names:
                nombres[a.asname or a.name] = (n.module, a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.asname:
                    modulos[a.asname] = a.name
    return nombres, modulos


def _resolver(archivo: str, llamada: ast.Call, indice):
    """La ``def`` a la que apunta una llamada, si está en el árbol. ``(archivo, nodo)``."""
    f = llamada.func
    nombres, modulos = _importados(archivo, indice)
    if isinstance(f, ast.Name):
        propia = _def_de_nivel_superior(archivo, f.id, indice)
        if propia is not None:
            return archivo, propia
        if f.id in nombres:
            modulo, original = nombres[f.id]
            destino = _archivo_de_modulo(modulo, indice)
            if destino:
                nodo = _def_de_nivel_superior(destino, original, indice)
                if nodo is not None:
                    return destino, nodo
    elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        alias = f.value.id
        modulo = None
        if alias in modulos:
            modulo = modulos[alias]
        elif alias in nombres:                       # `from pkg import mod` → mod.func()
            modulo = ".".join(nombres[alias])
        destino = _archivo_de_modulo(modulo, indice) if modulo else None
        if destino:
            nodo = _def_de_nivel_superior(destino, f.attr, indice)
            if nodo is not None:
                return destino, nodo
    return None


# ── El análisis ─────────────────────────────────────────────────────────────────

def _es_encolado(n: ast.Call) -> bool:
    return isinstance(n.func, ast.Attribute) and n.func.attr in _ENCOLAR


def _nombre_de_llamada(c: ast.Call) -> str | None:
    if isinstance(c.func, ast.Name):
        return c.func.id
    if isinstance(c.func, ast.Attribute):
        return c.func.attr
    return None


def _esperado(fn, encolado: ast.Call) -> bool:
    padres = {hijo: padre for padre in ast.walk(fn) for hijo in ast.iter_child_nodes(padre)}
    llamadas = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
    # Pasado directo al esperador: `esperar_tarea(task.delay(...), ...)`.
    padre = padres.get(encolado)
    if isinstance(padre, ast.Call) and _nombre_de_llamada(padre) == _ESPERADOR:
        return True
    if not (isinstance(padre, ast.Assign) and len(padre.targets) == 1
            and isinstance(padre.targets[0], ast.Name)):
        return False                                  # el AsyncResult se descarta
    var = padre.targets[0].id
    for c in llamadas:
        if _nombre_de_llamada(c) == _ESPERADOR and any(
                isinstance(a, ast.Name) and a.id == var for a in c.args):
            return True
    metodos = {c.func.attr for c in llamadas
               if isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name)
               and c.func.value.id == var}
    return ("get" in metodos) or ({"ready", "failed"} <= metodos)


def _encolados(archivo: str, fn, indice, visto=None, prof=0) -> list[tuple[str, bool]]:
    """``(dónde, esperado)`` de cada encolado alcanzable desde ``fn``."""
    visto = visto if visto is not None else set()
    clave = (archivo, fn.name, fn.lineno)
    if clave in visto or prof > _PROFUNDIDAD:
        return []
    visto.add(clave)
    out = []
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call):
            continue
        if _es_encolado(n):
            out.append((f"{archivo}:{n.lineno} en {fn.name}()", _esperado(fn, n)))
            continue
        destino = _resolver(archivo, n, indice)
        if destino is not None:
            out.extend(_encolados(destino[0], destino[1], indice, visto, prof + 1))
    return out


def _runners_registrados(indice):
    """``(archivo, nodo)`` del runner de cada ``Operation(...)`` del árbol."""
    out, sin_resolver = [], []
    for archivo, arbol in indice.items():
        for n in ast.walk(arbol):
            if not (isinstance(n, ast.Call) and _nombre_de_llamada(n) == "Operation"):
                continue
            runner = n.args[3] if len(n.args) > 3 else next(
                (k.value for k in n.keywords if k.arg == "runner"), None)
            if runner is None:
                continue
            destino = _resolver(archivo, ast.Call(func=runner, args=[], keywords=[]), indice)
            if destino is None:
                sin_resolver.append(f"{archivo}:{n.lineno}")
            else:
                out.append(destino)
    return out, sin_resolver


def _barrido(indice):
    """(runners, sin_resolver, {clave: encolados}, {clave: sin esperar})."""
    runners, sin_resolver = _runners_registrados(indice)
    que_encolan, sin_esperar = {}, {}
    for archivo, fn in runners:
        clave = f"{archivo}::{fn.name}"
        enc = _encolados(archivo, fn, indice)
        if enc:
            que_encolan[clave] = enc
        malos = [d for d, ok in enc if not ok]
        if malos:
            sin_esperar[clave] = malos
    return runners, sin_resolver, que_encolan, sin_esperar


_INDICE = _indice()
_RUNNERS, _SIN_RESOLVER, _QUE_ENCOLAN, _SIN_ESPERAR = _barrido(_INDICE)


# ── Tests ───────────────────────────────────────────────────────────────────────

def test_el_barrido_encuentra_runners_y_los_que_encolan():
    """Piso: un barrido vacío pasa en verde sin proteger nada."""
    assert len(_RUNNERS) >= 70, f"el barrido resolvió {len(_RUNNERS)} runners; esperaba ~80"
    assert "modules/social_dev/operations.py::_run_digepres_salud" in _QUE_ENCOLAN, (
        f"el barrido no ve que el runner de DIGEPRES encola; encontró {sorted(_QUE_ENCOLAN)}")


def test_todo_runner_registrado_se_resuelve():
    """Un runner que el barrido no puede leer es un runner que la regla no mira."""
    assert not _SIN_RESOLVER, f"registros con runner no resoluble: {_SIN_RESOLVER}"


def test_ningun_runner_encola_y_vuelve_sin_esperar():
    malos = {k: v for k, v in _SIN_ESPERAR.items() if k not in EXCEPCIONES}
    assert not malos, (
        "Estos runners encolan en Celery y devuelven sin esperar el desenlace. El console "
        "los marca «completado» con error=None mientras el worker sigue, y su fallo nunca "
        "llega a status.error. Usá shared.operations.worker.esperar_tarea, o declaralo en "
        "EXCEPCIONES con la razón:\n"
        + "\n".join(f"  {k}: {', '.join(v)}" for k, v in sorted(malos.items())))


def test_las_excepciones_no_estan_rancias():
    rancias = [k for k in EXCEPCIONES if k not in _SIN_ESPERAR]
    assert not rancias, f"EXCEPCIONES que ya no despachan-y-vuelven (borralas): {rancias}"
    assert all(r.strip() for r in EXCEPCIONES.values()), "toda excepción declara su razón"


def test_el_detector_distingue_despachar_de_esperar():
    """Prueba negativa sobre un árbol sintético: si el detector deja de ver el patrón malo
    —o empieza a marcar el bueno— los tests de arriba mienten en verde o en rojo."""
    fuente = '''
from shared.operations import Operation
from shared.operations.worker import esperar_tarea
from pkg.helpers import despacha

def _run_vuelve(params, user_id, set_phase):
    t = tarea.delay(force=True)
    return {"via": "worker", "task_id": t.id}

def _run_descarta(params, user_id, set_phase):
    tarea.apply_async()
    return {}

def _run_indirecto(params, user_id, set_phase):
    return despacha()

def _run_helper(params, user_id, set_phase):
    t = tarea.delay()
    return esperar_tarea(t, set_phase, espera_maxima_seg=1, latido_seg=1, al_vencer="x")

def _run_a_mano(params, user_id, set_phase):
    t = tarea.delay()
    while not t.ready():
        pass
    if t.failed():
        return {"error": "x"}
    return t.result

Operation("a", "", "", _run_vuelve, 1)
Operation("b", "", "", _run_descarta, 1)
Operation("c", "", "", _run_indirecto, 1)
Operation("d", "", "", runner=_run_helper, default_interval_hours=1)
Operation("e", "", "", _run_a_mano, 1)
'''
    ayudante = "def despacha():\n    tarea.delay()\n    return {}\n"
    indice = {"fake/ops.py": ast.parse(fuente), "pkg/helpers.py": ast.parse(ayudante)}
    runners, sin_resolver, que_encolan, sin_esperar = _barrido(indice)
    assert len(runners) == 5 and not sin_resolver
    assert set(que_encolan) == {f"fake/ops.py::_run_{x}" for x in
                                ("vuelve", "descarta", "indirecto", "helper", "a_mano")}
    assert set(sin_esperar) == {"fake/ops.py::_run_vuelve", "fake/ops.py::_run_descarta",
                                "fake/ops.py::_run_indirecto"}
    assert "pkg/helpers.py" in sin_esperar["fake/ops.py::_run_indirecto"][0]
