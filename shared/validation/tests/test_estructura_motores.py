"""REGLA ESTRUCTURAL: un motor de validación se invalida por su INSUMO, no por el reloj.

**El caso que la motivó.** La recalibración `02fcdd2` (2026-08-07) cambió el `overall_score`
de banca. El backtest tenía su próxima corrida agendada para el 26-ago. Entre esas dos fechas
producción sirvió un Gini de 0,4436 calculado con el score anterior, contra un deck que decía
0,1615 — el número correcto. Diecinueve días. Nadie lo vio porque nada en el sistema sabía
que el reporte había quedado huérfano de su insumo.

**Por qué un test y no una lección.** El mismo desacople estaba en los ocho motores, y
`sector_intel` ya tenía la cura (`sector-snapshot` dispara `sector-gate-e`) desde julio sin
que nadie la copiara. Este repo ya acumuló siete instancias de "un guard existe en un motor y
falta en el otro"; lo que funciona es leer el código con `ast` y exigir la regla.

**La regla, en tres partes.**

1. Todo reporte de validación persistido tiene un motor registrado
   (`shared.validation.frescura.MOTORES`) — o una excepción declarada abajo con su motivo.
2. Todo motor se recalcula por cascada (alguna operación lo tiene en `triggers`) — o declara
   `sin_cascada_motivo`, que es una afirmación revisable, no un olvido.
3. Todo motor sella su reporte con `sellar(...)`: sin huella, la cascada es una promesa que
   nadie puede verificar en la respuesta.

**Qué queda fuera del glob, y por qué** (declarado, no omitido): los motores que NO viven bajo
`modules/*/validation/` — el modelo de TPM (`macro_monitor/tpm_modeling`) y la cohorte
histórica de banca (`sib_historical_backtest.py`). El primero está en `FUERA_DEL_GLOB` con su
motivo; el segundo no persiste reporte (corre en vivo), así que no aparece.
"""
import ast
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parents[3]
MODULOS = RAIZ / "modules"

# Cómo se ve la clave de un reporte de validación persistido en `AppSetting`.
_CLAVE_VALIDACION = re.compile(r"^[a-z0-9_]*(backtest|gate_e|convergent_validity)[a-z0-9_]*$")

# Reportes de validación persistidos que NO tienen motor registrado, con el motivo. Entrar
# acá es una decisión que se defiende en revisión; no entrar y no registrar, un test rojo.
FUERA_DEL_GLOB = {
    "tpm_backtest": (
        "El modelo de TPM vive fuera de `modules/*/validation/` y es el ÚNICO motor del "
        "catálogo que ya se invalidaba por evento antes de esta regla: "
        "`bcrd-comunicados-sync` dispara `tpm-model-train`, que reentrena y re-backtestea "
        "junto. Su artefacto persistido es el modelo entrenado con su backtest adentro, no "
        "un reporte de Gate E aparte. Pendiente: darle huella de insumo como los demás."
    ),
}


def _archivos_py():
    for p in sorted(MODULOS.rglob("*.py")):
        if "/tests/" in str(p) or "__pycache__" in str(p):
            continue
        yield p


def _constantes_del_modulo(arbol: ast.Module):
    """{NOMBRE: "valor"} de las asignaciones string a nivel de módulo."""
    out = {}
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign) and isinstance(nodo.value, ast.Constant) \
                and isinstance(nodo.value.value, str):
            for destino in nodo.targets:
                if isinstance(destino, ast.Name):
                    out[destino.id] = nodo.value.value
    return out


def _resolver(nodo, constantes):
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    if isinstance(nodo, ast.Name):
        return constantes.get(nodo.id)
    return None


def _claves_de_appsetting(path: pathlib.Path):
    """(leídas, escritas) — claves de `AppSetting` que parecen reportes de validación.

    Escritas = `AppSetting(key=…)` (la construcción de la fila). Leídas = la comparación
    `AppSetting.key == …`. Se resuelven los literales y las constantes del propio archivo;
    un nombre importado de otro módulo no se resuelve y no cuenta — lo que importa acá es
    dónde se ESCRIBE, y eso siempre está junto a la constante.
    """
    arbol = ast.parse(path.read_text(encoding="utf-8"))
    constantes = _constantes_del_modulo(arbol)
    leidas, escritas = set(), set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) \
                and nodo.func.id == "AppSetting":
            for kw in nodo.keywords:
                if kw.arg == "key":
                    v = _resolver(kw.value, constantes)
                    if v and _CLAVE_VALIDACION.match(v):
                        escritas.add(v)
        if isinstance(nodo, ast.Compare) and isinstance(nodo.left, ast.Attribute) \
                and nodo.left.attr == "key" and isinstance(nodo.left.value, ast.Name) \
                and nodo.left.value.id == "AppSetting":
            for comp in nodo.comparators:
                v = _resolver(comp, constantes)
                if v and _CLAVE_VALIDACION.match(v):
                    leidas.add(v)
    return leidas, escritas


def _mapa_de_escrituras() -> dict:
    """clave → [archivos que la escriben]."""
    mapa: dict = {}
    for path in _archivos_py():
        _, escritas = _claves_de_appsetting(path)
        for clave in escritas:
            mapa.setdefault(clave, []).append(path.relative_to(RAIZ))
    return mapa


def _motores():
    import app.main  # noqa: F401 — auto-registra las operaciones y los motores reales
    from shared.validation.frescura import MOTORES

    return MOTORES


# ── 1. Todo reporte persistido tiene motor ────────────────────────

def test_todo_reporte_de_validacion_tiene_motor_registrado():
    motores = _motores()
    registradas = {m.clave for m in motores.values()}
    huerfanas = {
        clave: archivos for clave, archivos in _mapa_de_escrituras().items()
        if clave not in registradas and clave not in FUERA_DEL_GLOB
    }
    assert not huerfanas, (
        "Estos reportes de validación se persisten sin motor registrado, así que nada sabe "
        "cuándo quedan huérfanos de su insumo:\n"
        + "\n".join(f"  · {k} — {[str(a) for a in v]}" for k, v in huerfanas.items())
        + "\nRegistralos con `registrar_motor(MotorValidacion(...))` en el `operations.py` "
          "del módulo, o declaralos en FUERA_DEL_GLOB con su motivo."
    )


def test_las_excepciones_declaran_un_motivo_de_verdad():
    """Una excepción sin motivo es un olvido con permiso."""
    for clave, motivo in FUERA_DEL_GLOB.items():
        assert len(motivo.split()) >= 12, f"{clave}: el motivo tiene que explicar, no rotular."


# ── 2. Todo motor se recalcula por cascada (o declara por qué no) ──

def test_todo_motor_se_dispara_por_cascada_o_declara_el_motivo():
    motores = _motores()
    from shared.operations import OPERATIONS

    sin_cura = []
    for eje, motor in sorted(motores.items()):
        assert motor.operacion in OPERATIONS, (
            f"{eje}: declara la operación '{motor.operacion}', que no está registrada.")
        disparadores = [n for n, op in OPERATIONS.items()
                        if motor.operacion in (op.triggers or [])]
        if not disparadores and not (motor.sin_cascada_motivo or "").strip():
            sin_cura.append(eje)
    assert not sin_cura, (
        "Estos motores dependen SOLO del reloj: ninguna operación los dispara y no declaran "
        f"por qué no corresponde: {sin_cura}. Es exactamente cómo producción sirvió el Gini "
        "de 0,44 durante 19 días."
    )


def test_las_operaciones_declaradas_como_disparadoras_existen_y_disparan():
    """`disparado_por` es documentación: si miente, engaña más que el silencio."""
    motores = _motores()
    from shared.operations import OPERATIONS

    for eje, motor in sorted(motores.items()):
        for nombre in motor.disparado_por:
            assert nombre in OPERATIONS, f"{eje}: '{nombre}' no es una operación registrada."
            assert motor.operacion in (OPERATIONS[nombre].triggers or []), (
                f"{eje}: declara que '{nombre}' lo dispara, pero esa operación no tiene "
                f"'{motor.operacion}' en sus triggers.")


# ── 3. Todo motor sella su reporte ────────────────────────────────

def test_todo_motor_sella_su_reporte_con_la_huella():
    motores = _motores()
    mapa = _mapa_de_escrituras()
    sin_sello = []
    for eje, motor in sorted(motores.items()):
        # Se busca el archivo que ESCRIBE el reporte (por AST, no por substring: la clave
        # de banca, `backtest_report`, está contenida en la de seguros y la de pensiones —
        # buscar por texto daba por sellado un motor que no lo estaba).
        escritores = mapa.get(motor.clave, [])
        if not escritores:
            sin_sello.append(f"{eje}: no se encontró dónde se escribe '{motor.clave}'")
            continue
        for rel in escritores:
            if "sellar(" not in (RAIZ / rel).read_text(encoding="utf-8"):
                sin_sello.append(f"{eje}: {rel} escribe el reporte sin `sellar(`")
    assert not sin_sello, (
        "Un reporte sin huella no se puede declarar obsoleto al leerlo:\n  "
        + "\n  ".join(sin_sello)
    )


def test_el_reporte_se_escribe_por_una_sola_puerta():
    """Dos puertas de escritura = una que se actualiza y otra que se olvida.

    Pasó literalmente: el backtest de seguros se persistía desde la operación de consola Y
    desde `POST /insurance-intel/backtest`, y ninguna de las dos estampaba fecha. Era el
    único reporte del catálogo del que no se podía saber de cuándo era la cifra servida.
    """
    motores = _motores()
    mapa = _mapa_de_escrituras()
    multiples = {m.clave: mapa.get(m.clave, []) for m in motores.values()
                 if len(mapa.get(m.clave, [])) > 1}
    assert not multiples, (
        "Estos reportes se escriben desde más de un archivo:\n"
        + "\n".join(f"  · {k} — {[str(a) for a in v]}" for k, v in multiples.items())
        + "\nDejá una sola puerta (un `persistir_*` en el `operations.py` del módulo) y que "
          "la ruta la llame."
    )
