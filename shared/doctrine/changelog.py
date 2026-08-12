"""Registro de cambios de METODOLOGÍA — lectura de ``changelog.yaml``.

**Qué problema resuelve.** Cuando la vara cambia, las entidades se mueven sin haber hecho
nada. El histórico ya marca esos movimientos (``RatingAction.metodologica``, derivada de que
cambie ``model_version``), pero esa marca dice QUE fue metodológico y no CUÁL cambio ni POR
QUÉ. Sin eso, un cliente que compara dos informes ve una cifra distinta y no hay con qué
responderle; y una recalibración se lee en el histórico como una tanda de downgrades.

**Por qué acá y no en un módulo nuevo.** ``shared/doctrine`` ya es el documento de control
versionado que el código lee y que se cambia por PR, no por edición de código. Un cambio de
metodología es exactamente eso.

**Lo que este módulo NO hace:** no recalcula el pasado. Las cifras de impacto son las que se
afirmaron al publicar el cambio y se sirven etiquetadas como tales — recalcularlas contra el
panel de hoy daría un número distinto cada día y ninguno sería el que el cliente recibió.
"""
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

_RUTA = Path(__file__).resolve().parent / "changelog.yaml"

# Campos que toda entrada debe traer para ser auditable. Sin `pr` el cambio no se puede
# contrastar contra el código, y una entrada así no es un registro: es una afirmación.
CAMPOS_REQUERIDOS = ("id", "fecha_efectiva", "sectores", "titulo", "que_cambio", "por_que", "pr")


@lru_cache(maxsize=1)
def cargar() -> Dict[str, Any]:
    # `types-PyYAML` no está en el lock; el resto del repo arrastra este error en el
    # baseline y un archivo nuevo no debería hacer crecer la deuda.
    import yaml  # type: ignore[import-untyped]

    with open(_RUTA, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def cambios(sector: Optional[str] = None,
            desde: Optional[date] = None,
            hasta: Optional[date] = None) -> List[Dict[str, Any]]:
    """Cambios aplicables, del más reciente al más antiguo.

    *sector* filtra por clave de producto (``banking``/``insurance``/``pension``); *desde* y
    *hasta* acotan por fecha efectiva — es la consulta que responde «¿qué cambió entre el
    informe que le mandé en junio y el de ahora?».
    """
    out = []
    for c in cargar().get("cambios") or []:
        if sector and sector not in (c.get("sectores") or []):
            continue
        f = _fecha(c.get("fecha_efectiva"))
        if f is None or (desde and f < desde) or (hasta and f > hasta):
            continue
        out.append(c)
    return sorted(out, key=lambda c: str(c.get("fecha_efectiva")), reverse=True)


def _prs(v: Any) -> List[int]:
    """``pr`` admite un entero o una lista; se publica siempre como lista."""
    if isinstance(v, list):
        return [int(x) for x in v]
    return [int(v)]


def _fecha(v: Any) -> Optional[date]:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


def atribuir(sector: str, period_end: Any,
             previous_period_end: Any = None) -> List[Dict[str, Any]]:
    """Cambios de metodología vigentes ENTRE dos cortes — a qué atribuir un movimiento.

    Devuelve las entradas cuya fecha efectiva cae en ``(previous_period_end, period_end]``.
    Sin corte previo no se atribuye nada: no se puede afirmar que un cambio explica un
    movimiento cuando no hay con qué comparar.

    >>> atribuir("insurance", "2026-08-31", "2026-07-31")[0]["id"]
    '2026-08-12-solo-se-ordena-lo-comparable'
    >>> atribuir("insurance", "2026-08-31") == []
    True
    """
    hasta = _fecha(period_end)
    desde = _fecha(previous_period_end)
    if hasta is None or desde is None:
        return []
    return [c for c in cambios(sector) if desde < (_fecha(c["fecha_efectiva"]) or hasta) <= hasta]


def resumen_publicable(sector: Optional[str] = None) -> Dict[str, Any]:
    """Payload para la API y para el pie de un informe.

    Cada impacto viaja con la etiqueta de CUÁNDO se midió: es lo que afirmamos al publicar,
    no una lectura del panel de hoy.
    """
    filas = []
    for c in cambios(sector):
        imp = (c.get("impacto") or {}).get("medido_al_publicar")
        filas.append({
            "id": c["id"],
            "fecha_efectiva": str(c["fecha_efectiva"]),
            "sectores": c.get("sectores") or [],
            "titulo": c["titulo"],
            "que_cambio": c["que_cambio"],
            "por_que": c["por_que"],
            "impacto_medido_al_publicar": imp,
            # Siempre lista: un cambio puede haber entrado repartido en varios PRs (pasó con
            # 2026-08-12, que llegó mitad por #701 y mitad por #702). Un consumidor no debería
            # tener que distinguir entre un entero y una lista para citar la fuente.
            "pr": _prs(c["pr"]),
            "corrige": c.get("corrige"),
        })
    return {
        "version": cargar().get("version"),
        "sector": sector,
        "cambios": filas,
        "nota": ("Las cifras de impacto son las medidas AL PUBLICAR cada cambio, no una "
                 "lectura del panel actual: describen el efecto en su momento. El estado "
                 "vigente se consulta en el panel."),
    }
