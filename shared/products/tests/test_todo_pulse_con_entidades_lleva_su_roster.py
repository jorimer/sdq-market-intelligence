"""REGLA ESTRUCTURAL: el Pulse de un eje con entidades nombradas le pasa su ROSTER al sensor.

**El caso (2026-09-14, #1169).** `insurance_intel` armaba el `ProductSnapshot` del Pulse sin
`entity_roster`. El ensamblador corre `enforce_anonymized(..., entity_roster=snapshot.entity_roster)`
sobre el payload y sobre el TEXTO de todo nivel `system`, pero con el roster vacío el sensor solo
mira las claves reservadas: un Pulse cuya prosa nombrara una aseguradora pasaba sin marca. No
falla nada — el sensor dice que sí a todo, que es la forma en que un guard se muere en silencio.
La auditoría encontró el mismo hueco en otros tres ejes.

**La regla.** En el `snapshot()` de todo producto registrado, cada `ProductSnapshot(...)` de
SISTEMA —el que no nombra entidad: `entity_name` ausente, `None`, o una variable que puede ser
`None`— pasa `entity_roster=` con algo que no sea un literal vacío. O el eje está en
`SIN_ROSTER_DECLARADO` con el motivo: un eje cuyo sujeto es el país o un sector no tiene a quién
anonimizar, y eso se DECLARA en vez de saltearlo.

Se lee el código y no se ejecuta el snapshot: ejecutarlo exige sembrar el dato de cada eje, y un
Pulse sin dato devuelve un roster vacío por la razón correcta. Que el roster traiga NOMBRES REALES
lo prueba cada eje en su propio test, ensamblando un Pulse que nombra a una entidad.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Dict, List, Optional

import pytest

#: Ejes cuyo Pulse no lleva roster, y POR QUÉ. Un eje que entra acá sin motivo es un hueco
#: con otro nombre: el motivo tiene que decir qué no hay que anonimizar.
SIN_ROSTER_DECLARADO: Dict[str, str] = {
    "trade": (
        "Nacional: el sujeto del nivel nombrado es República Dominicana. Los socios comerciales "
        "y los capítulos HS son dimensiones del dato, no sujetos calificados de ningún nivel."),
    "tourism": "El sujeto es el destino nacional; ningún nivel nombra una firma.",
    "free_zones": "El sujeto es el sector de zonas francas; ningún nivel nombra una firma.",
    "energy": "El sujeto es el sistema eléctrico nacional; ningún nivel nombra una firma.",
    "telecom": "El sujeto es el mercado nacional de telecomunicaciones; ningún nivel nombra una firma.",
    "construction": "El sujeto es el sector construcción; ningún nivel nombra una firma.",
    "agribusiness": "El sujeto es el sector agropecuario; ningún nivel nombra una firma.",
    "economic_structure": (
        "El sujeto es la economía por sector de origen (Valor Agregado); no hay firmas."),
    "esg": "Resiliencia climática nacional: el sujeto es el país y no se nombran pares.",
    "macro_forecast": (
        "Los tres niveles son de sistema y el sujeto es el país: no hay un nivel nombrado cuyo "
        "contenido pueda filtrarse al Pulse."),
    "monetary_policy": (
        "Los tres niveles son de sistema y el sujeto es la política del BCRD: no hay entidades."),
    "law": (
        "El sujeto es un instrumento normativo, no un padrón de entidades calificadas. Los "
        "organismos responsables de una brecha los nombra la propia ley."),
    "valuation": (
        "El Pulse no tiene producción real: `snapshot(pulse)` exige una entidad y sin ella lanza; "
        "con ella devuelve `entity_name` y el ensamblador lo veta. Cuando exista un Pulse de "
        "valuación, su roster son los bancos y esta excepción tiene que salir."),
}


# ── El detector ──

def _puede_ser_none(expr: Optional[ast.expr], asignaciones: Dict[str, List[ast.expr]]) -> bool:
    if expr is None:
        return True  # `entity_name` ausente → el default del contrato es None
    if isinstance(expr, ast.Constant):
        return expr.value is None
    if isinstance(expr, ast.IfExp):
        return (_puede_ser_none(expr.body, asignaciones)
                or _puede_ser_none(expr.orelse, asignaciones))
    if isinstance(expr, ast.Name):
        return any(_puede_ser_none(v, {}) for v in asignaciones.get(expr.id, []))
    return False


def _es_vacio(expr: ast.expr) -> bool:
    if isinstance(expr, (ast.Tuple, ast.List, ast.Set)):
        return not expr.elts
    if isinstance(expr, ast.Constant):
        return not expr.value
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
        return expr.func.id in {"tuple", "list", "set", "frozenset"} and not expr.args
    return False


def huecos_de_roster(fuente: str) -> tuple:
    """`(n_snapshots_de_sistema, [líneas sin roster])` de la función `snapshot` en `fuente`."""
    arbol = ast.parse(textwrap.dedent(fuente))
    func = next(n for n in ast.walk(arbol)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "snapshot")
    asignaciones: Dict[str, List[ast.expr]] = {}
    for n in ast.walk(func):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    asignaciones.setdefault(t.id, []).append(n.value)
    de_sistema = 0
    huecos: List[int] = []
    for n in ast.walk(func):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "ProductSnapshot"):
            continue
        kw = {k.arg: k.value for k in n.keywords if k.arg}
        if not _puede_ser_none(kw.get("entity_name"), asignaciones):
            continue
        de_sistema += 1
        roster = kw.get("entity_roster")
        if roster is None or _es_vacio(roster):
            huecos.append(n.lineno)
    return de_sistema, sorted(huecos)


# ── El detector no nace ciego ──

_COMO_ERA_SEGUROS = '''
def snapshot(self, tier, period, scope=None):
    if tier == ProductTier.pulse:
        return ProductSnapshot(tier=tier, period=period, payload={}, entity_name=None)
    entity = None if tier == ProductTier.pulse else "X"
    return ProductSnapshot(tier=tier, period=period, payload={}, entity_name=entity,
                           entity_roster=())
'''

_CON_ROSTER = '''
def snapshot(self, tier, period, scope=None):
    if tier == ProductTier.pulse:
        return ProductSnapshot(tier=tier, period=period, payload={}, entity_name=None,
                               entity_roster=_roster(db))
    return ProductSnapshot(tier=tier, period=period, payload={}, entity_name="Banco X")
'''


def test_el_detector_caza_el_pulse_sin_roster_y_el_de_roster_vacio():
    assert huecos_de_roster(_COMO_ERA_SEGUROS) == (2, [4, 6])


def test_el_detector_deja_pasar_el_roster_computado_y_no_cuenta_los_niveles_nombrados():
    assert huecos_de_roster(_CON_ROSTER) == (1, [])


# ── La regla sobre el catálogo real ──

def _productos_con_pulse_de_sistema():
    import app.main  # noqa: F401 — auto-registra todos los productos
    from shared.products import Granularity, ProductTier
    from shared.products.registry import PRODUCT_CATALOG, get_product

    out = []
    for e in PRODUCT_CATALOG:
        p = get_product(e.sector_key, None)
        if p is None:
            continue
        nivel = p.product_manifest().levels.get(ProductTier.pulse)
        if nivel is not None and nivel.granularity == Granularity.system:
            out.append((e.sector_key, p))
    return out


def test_todo_pulse_de_un_eje_con_entidades_le_pasa_su_roster_al_sensor():
    fallos = []
    for clave, p in _productos_con_pulse_de_sistema():
        if clave in SIN_ROSTER_DECLARADO:
            continue
        cls = type(p)
        de_sistema, huecos = huecos_de_roster(inspect.getsource(cls.snapshot))
        archivo = inspect.getsourcefile(cls)
        base = inspect.getsourcelines(cls.snapshot)[1] - 1
        if de_sistema == 0:
            fallos.append(f"{clave} ({archivo}): `snapshot()` no arma ningún ProductSnapshot de "
                          "sistema que este test pueda leer — declaralo o hacé legible el Pulse")
        for linea in huecos:
            fallos.append(f"{clave}: {archivo}:{base + linea} arma un snapshot de sistema sin "
                          "`entity_roster` (o con uno vacío)")
    assert not fallos, "\n  ".join(
        ["Pulses que el sensor de anonimización no puede vigilar: con el roster vacío solo mira "
         "claves reservadas, y un texto que nombra una entidad pasa. Pasá el roster del eje o "
         "declaralo en SIN_ROSTER_DECLARADO con el motivo:"] + fallos)


def test_la_lista_de_excepciones_no_tiene_ejes_fantasma():
    claves = {k for k, _ in _productos_con_pulse_de_sistema()}
    fantasmas = sorted(set(SIN_ROSTER_DECLARADO) - claves)
    assert not fantasmas, (f"Excepciones para ejes que no tienen un Pulse de sistema registrado: "
                           f"{fantasmas}. Una excepción vieja tapa al eje que la reemplace.")


@pytest.mark.parametrize("clave", sorted(SIN_ROSTER_DECLARADO))
def test_cada_excepcion_explica_en_vez_de_rotular(clave):
    assert len(SIN_ROSTER_DECLARADO[clave].split()) >= 8
