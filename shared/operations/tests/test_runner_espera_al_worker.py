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

_VERBOS = ("get", "post", "put", "delete", "patch")
_PORTADORES = ("router", "app")

_POR_DOCUMENTO = (
    "Es una lectura POR DOCUMENTO, y un encargo puede tener varias en paralelo: no cabe en "
    "una operación de consola, que admite una corrida a la vez. El trabajo es su fila "
    "BrandExtraction: el worker registra ahí el error (`jobs._fail`) o la cancelación, y la "
    "pantalla lo lee con GET .../extractions/{id}/status. Lo que sigue abierto es el "
    "vigilante de un worker que MUERE sin escribir (queda en `reading`), que es otro hueco.")

#: ``"archivo::función"`` → por qué esa RUTA puede encolar y responder sin que el desenlace
#: llegue a un estado que alguien lea. Una ruta no puede esperar al worker dentro del
#: request (el proxy corta a los ~270 s): lo correcto es disparar una operación de consola
#: cuyo runner espere, como hace ``POST /banking-score/data/rescore``.
EXCEPCIONES_RUTAS: dict[str, str] = {
    "modules/brand_intel/api/router.py::ingest_pdf": _POR_DOCUMENTO,
    "modules/brand_intel/api/router.py::resume_extraction": _POR_DOCUMENTO,
}


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


_CACHE_IMPORTS: dict[tuple[int, str], tuple[dict, dict]] = {}


def _importados(archivo: str, indice) -> tuple[dict, dict]:
    """(nombre → (módulo, nombre original), alias → módulo) de TODO import del archivo,
    incluidos los que viven dentro de funciones — el patrón del repo es importar tarde.

    Cacheado por (índice, archivo): sin caché, barrer ~300 rutas releía el árbol de cada
    archivo en cada llamada resuelta y el test pasaba de 13 s a 100 s."""
    clave = (id(indice), archivo)
    if clave not in _CACHE_IMPORTS:
        _CACHE_IMPORTS[clave] = _leer_imports(archivo, indice)
    return _CACHE_IMPORTS[clave]


def _leer_imports(archivo: str, indice) -> tuple[dict, dict]:
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


def _clasificar(pares, indice):
    """({clave: encolados}, {clave: encolados sin esperar}) de cada ``(archivo, def)``."""
    que_encolan, sin_esperar = {}, {}
    for archivo, fn in pares:
        clave = f"{archivo}::{fn.name}"
        enc = _encolados(archivo, fn, indice)
        if enc:
            que_encolan[clave] = enc
        malos = [d for d, ok in enc if not ok]
        if malos:
            sin_esperar[clave] = malos
    return que_encolan, sin_esperar


def _barrido(indice):
    """(runners, sin_resolver, {clave: encolados}, {clave: sin esperar})."""
    runners, sin_resolver = _runners_registrados(indice)
    return (runners, sin_resolver, *_clasificar(runners, indice))


def _rutas_declaradas(indice):
    """``(archivo, def)`` de toda función decorada con ``@router.<verbo>``/``@app.<verbo>``."""
    out = []
    for archivo, arbol in indice.items():
        for n in ast.walk(arbol):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in n.decorator_list:
                c = d.func if isinstance(d, ast.Call) else d
                if (isinstance(c, ast.Attribute) and c.attr in _VERBOS
                        and isinstance(c.value, ast.Name) and c.value.id in _PORTADORES):
                    out.append((archivo, n))
                    break
    return out


def _barrido_de_rutas(indice):
    """(rutas, {clave: encolados}, {clave: sin esperar})."""
    rutas = _rutas_declaradas(indice)
    return (rutas, *_clasificar(rutas, indice))


_INDICE = _indice()
_RUNNERS, _SIN_RESOLVER, _QUE_ENCOLAN, _SIN_ESPERAR = _barrido(_INDICE)
_RUTAS, _RUTAS_QUE_ENCOLAN, _RUTAS_SIN_ESPERAR = _barrido_de_rutas(_INDICE)


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


def test_el_barrido_de_rutas_ve_las_que_encolan():
    """Piso: si el barrido deja de ver la ruta de brand_intel, que encola de verdad, la
    regla de abajo pasaría en verde sin mirar nada."""
    assert len(_RUTAS) >= 300, f"el barrido encontró {len(_RUTAS)} rutas"
    assert "modules/brand_intel/api/router.py::ingest_pdf" in _RUTAS_QUE_ENCOLAN, (
        f"el barrido no ve que ingest_pdf encola; vio {sorted(_RUTAS_QUE_ENCOLAN)}")


def test_ninguna_ruta_encola_sin_que_el_desenlace_llegue_a_un_estado():
    malas = {k: v for k, v in _RUTAS_SIN_ESPERAR.items() if k not in EXCEPCIONES_RUTAS}
    assert not malas, (
        "Estas rutas encolan en Celery y responden: si el worker falla, el error no llega a "
        "ningún estado que alguien lea. Disparen una operación de consola cuyo runner use "
        "shared.operations.worker.esperar_tarea (ver `rescore`), o declárenlas en "
        "EXCEPCIONES_RUTAS con la razón:\n"
        + "\n".join(f"  {k}: {', '.join(v)}" for k, v in sorted(malas.items())))


def test_las_excepciones_de_rutas_no_estan_rancias():
    rancias = [k for k in EXCEPCIONES_RUTAS if k not in _RUTAS_SIN_ESPERAR]
    assert not rancias, f"EXCEPCIONES_RUTAS que ya no encolan sin esperar: {rancias}"
    assert all(r.strip() for r in EXCEPCIONES_RUTAS.values())


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
