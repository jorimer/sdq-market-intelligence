"""Un aviso in-app y su marcador de dedup se escriben en UNA transacción, o no se escribe ninguno.

**El defecto que lo obligó.** El 2026-09-10 PostgreSQL rechazó el marcador de dedup de las
alertas (#1165) con la notificación ya comprometida: cada barrido volvía a avisar lo mismo.
Al arreglarlo, el mismo orden estaba en SEIS sitios más —la auditoría de frescura (tres
bucles), la fuente congelada, la frescura de la TPM y «Listo para publicar»— y en este último
al revés: marcador primero, así que un aviso que no entraba lo silenciaba para siempre
(ese marcador no vence). Dos órdenes, un mismo defecto: dos escrituras que tienen que ir
juntas, comprometidas por separado.

**La regla.** Toda función que llame a ``notification_service.create`` Y a un marcador de dedup
(``.marcar`` o la fachada ``_mark_notified``) pasa ``commit=False`` a los dos y tiene su
``rollback``. O declara su excepción en :data:`EXCEPCIONES`, con el motivo.

**Qué queda afuera**, dicho para que nadie lo lea como cobertura:

- Un aviso y un marcador en funciones DISTINTAS (un helper que avisa, llamado desde la que
  marca). El chequeo es por función; ese caso se ve en el test de comportamiento del consumidor.
- ``notification_service`` importado con otro nombre.
- Canales irreversibles (correo, webhook). No se pueden deshacer con un rollback: van DESPUÉS
  del commit, y lo que se registra primero es que salieron (ver `shared/alerts/digest.py`).

Se lee el código con ``ast`` y no se importa: la regla vale también para un módulo que no
arranque en el entorno de test.
"""
import ast
import pathlib
from typing import Dict, List, Tuple

RAIZ = pathlib.Path(__file__).resolve().parents[2]

#: Mismo criterio que `test_toda_ruta_recibe_su_path.py`, y contra la ruta RELATIVA: contra la
#: absoluta, correr el test dentro de un worktree excluía el repo entero.
EXCLUIDOS = (".venv", "/tests/", ".claude/worktrees", "node_modules", "/.git/")

#: (archivo relativo a la raíz, función) → por qué ESA función puede comprometer por separado.
EXCEPCIONES: Dict[Tuple[str, str], str] = {}

#: Los sitios que existían al escribir la regla. Si el barrido deja de encontrarlos, el
#: barrido se quedó ciego — no es que el defecto haya desaparecido.
CONOCIDOS = {
    ("shared/alerts/entrega.py", "entregar"),
    ("shared/operations/freshness.py", "run_freshness_audit"),
    ("shared/operations/freshness.py", "_audit_sovereign_ratings"),
    ("shared/operations/freshness.py", "_audit_publications"),
    ("shared/operations/fuentes_congeladas.py", "auditar_fuentes_de_los_ejes"),
    ("shared/products/service.py", "_notify_publishable_transitions"),
    ("modules/macro_monitor/comunicados/freshness.py", "audit_comunicados_freshness"),
}

_FUNCIONES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _llamadas_propias(fn: ast.AST) -> List[ast.Call]:
    """Las llamadas del cuerpo de *fn*, sin entrar en funciones anidadas: esas se juzgan solas."""
    llamadas: List[ast.Call] = []
    pendientes = list(ast.iter_child_nodes(fn))
    while pendientes:
        n = pendientes.pop()
        if isinstance(n, (*_FUNCIONES, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(n, ast.Call):
            llamadas.append(n)
        pendientes.extend(ast.iter_child_nodes(n))
    return llamadas


def _es_aviso(c: ast.Call) -> bool:
    return (isinstance(c.func, ast.Attribute) and c.func.attr == "create"
            and isinstance(c.func.value, ast.Name) and c.func.value.id == "notification_service")


def _es_marcador(c: ast.Call) -> bool:
    if isinstance(c.func, ast.Attribute):
        return c.func.attr in ("marcar", "_mark_notified")
    return isinstance(c.func, ast.Name) and c.func.id == "_mark_notified"


def _no_compromete(c: ast.Call) -> bool:
    return any(k.arg == "commit" and isinstance(k.value, ast.Constant) and k.value.value is False
               for k in c.keywords)


def _es_rollback(c: ast.Call) -> bool:
    return isinstance(c.func, ast.Attribute) and c.func.attr == "rollback"


def juzgar(fuente: str, rel: str) -> Tuple[List[Tuple[str, str]], List[str]]:
    """``(sitios, faltas)`` de *fuente*: las funciones que avisan y marcan, y lo que les falta."""
    sitios: List[Tuple[str, str]] = []
    faltas: List[str] = []
    for fn in ast.walk(ast.parse(fuente)):
        if not isinstance(fn, _FUNCIONES):
            continue
        llamadas = _llamadas_propias(fn)
        avisos = [c for c in llamadas if _es_aviso(c)]
        marcadores = [c for c in llamadas if _es_marcador(c)]
        if not (avisos and marcadores):
            continue
        sitios.append((rel, fn.name))
        if (rel, fn.name) in EXCEPCIONES:
            continue
        for c in avisos + marcadores:
            if not _no_compromete(c):
                faltas.append(f"{rel}:{c.lineno} {fn.name}(): {ast.unparse(c.func)}(...) "
                              f"compromete por su cuenta — pasale commit=False")
        if not any(_es_rollback(c) for c in llamadas):
            faltas.append(f"{rel}:{fn.lineno} {fn.name}(): sin rollback — un commit que falla "
                          f"deja la sesión inutilizable para el siguiente aviso")
    return sitios, faltas


def _barrido() -> Tuple[List[Tuple[str, str]], List[str]]:
    sitios: List[Tuple[str, str]] = []
    faltas: List[str] = []
    for f in sorted(RAIZ.rglob("*.py")):
        rel = f.relative_to(RAIZ).as_posix()
        if any(x in "/" + rel for x in EXCLUIDOS):
            continue
        try:
            fuente = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:                          # pragma: no cover - defensivo
            continue
        if "notification_service" not in fuente:
            continue
        try:
            s, fl = juzgar(fuente, rel)
        except SyntaxError:                                 # pragma: no cover - defensivo
            continue
        sitios.extend(s)
        faltas.extend(fl)
    return sitios, faltas


def test_el_barrido_encuentra_los_sitios_que_avisan_y_marcan():
    """Un barrido vacío pasa en verde sin comprobar nada."""
    sitios, _ = _barrido()
    faltan = CONOCIDOS - set(sitios)
    assert not faltan, f"el barrido dejó de ver sitios que existen: {sorted(faltan)}"


def test_todo_aviso_entra_con_su_marcador_en_una_transaccion():
    sitios, faltas = _barrido()
    assert faltas == [], (
        "aviso y marcador de dedup comprometidos por separado — si el segundo no entra, el "
        "primero queda escrito (re-spam, o silencio permanente si el marcador va primero):\n  "
        + "\n  ".join(faltas))
    rancias = set(EXCEPCIONES) - set(sitios)
    assert not rancias, f"excepciones declaradas sobre sitios que ya no existen: {sorted(rancias)}"


# ── Prueba negativa: el patrón viejo SE MARCA ────────────────────────────────────
# Sin esto, un `_es_aviso` que no reconozca la llamada deja el test anterior en verde sobre
# el código roto. Los dos fragmentos son los órdenes reales que había antes del arreglo.

_VIEJO_AVISO_PRIMERO = '''
def auditar(db, admin_ids, clave):
    try:
        for uid in admin_ids:
            notification_service.create(db, user_id=uid, type="warning", title="t")
        _mark_notified(db, clave)
    except Exception:
        db.rollback()
'''

_VIEJO_MARCADOR_PRIMERO = '''
def avisar(db, claves, admin_ids):
    for clave in claves:
        _DEDUP.marcar(db, clave)
    for uid in admin_ids:
        notification_service.create(db, user_id=uid, type="success", title="t")
'''

_CORRECTO = '''
def auditar(db, admin_ids, clave):
    try:
        for uid in admin_ids:
            notification_service.create(db, user_id=uid, type="warning", title="t",
                                        commit=False)
        _mark_notified(db, clave, commit=False)
        db.commit()
    except Exception:
        db.rollback()
'''


def test_prueba_negativa_el_aviso_comprometido_antes_del_marcador_se_marca():
    sitios, faltas = juzgar(_VIEJO_AVISO_PRIMERO, "x.py")
    assert sitios == [("x.py", "auditar")]
    assert len(faltas) == 2, faltas


def test_prueba_negativa_el_marcador_comprometido_antes_del_aviso_se_marca():
    sitios, faltas = juzgar(_VIEJO_MARCADOR_PRIMERO, "x.py")
    assert sitios == [("x.py", "avisar")]
    assert len(faltas) == 3, faltas        # marcar, create, y sin rollback


def test_la_forma_correcta_no_se_marca():
    sitios, faltas = juzgar(_CORRECTO, "x.py")
    assert sitios == [("x.py", "auditar")]
    assert faltas == []
